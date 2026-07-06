#!/usr/bin/env python3
"""Check whether two SRT files have matching subtitle timing."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


TIMING_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})(?:\s+.*)?$"
)


class SrtFormatError(ValueError):
    """Raised when an SRT file cannot be parsed."""


@dataclass(frozen=True)
class SrtBlock:
    ordinal: int
    index: int
    start_ms: int
    end_ms: int
    start_text: str
    end_text: str


@dataclass(frozen=True)
class Mismatch:
    ordinal: int
    reason: str
    left: str
    right: str
    delta_ms: int | None = None


@dataclass(frozen=True)
class AlignmentResult:
    left_path: str
    right_path: str
    left_blocks: int
    right_blocks: int
    tolerance_ms: int
    ignore_index: bool
    aligned: bool
    mismatches: list[Mismatch]


def parse_timestamp(value: str) -> int:
    normalized = value.replace(".", ",")
    try:
        hhmmss, millis = normalized.split(",", 1)
        hours, minutes, seconds = (int(part) for part in hhmmss.split(":"))
        milliseconds = int(millis)
    except ValueError as exc:
        raise SrtFormatError(f"invalid timestamp: {value}") from exc

    if minutes >= 60 or seconds >= 60 or milliseconds >= 1000:
        raise SrtFormatError(f"invalid timestamp range: {value}")

    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise OSError(f"failed to read {path}: {exc}") from exc


def parse_srt(path: Path) -> list[SrtBlock]:
    text = read_text(path)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise SrtFormatError(f"{path}: empty SRT file")

    blocks: list[SrtBlock] = []
    for ordinal, raw_block in enumerate(re.split(r"\n{2,}", normalized), start=1):
        lines = [line.strip() for line in raw_block.split("\n")]
        if len(lines) < 2:
            raise SrtFormatError(f"{path}: block {ordinal} has fewer than 2 lines")

        try:
            index = int(lines[0])
        except ValueError as exc:
            raise SrtFormatError(
                f"{path}: block {ordinal} index is not an integer: {lines[0]!r}"
            ) from exc

        match = TIMING_RE.match(lines[1])
        if not match:
            raise SrtFormatError(
                f"{path}: block {ordinal} timing line is invalid: {lines[1]!r}"
            )

        start_text = match.group("start")
        end_text = match.group("end")
        start_ms = parse_timestamp(start_text)
        end_ms = parse_timestamp(end_text)
        if start_ms > end_ms:
            raise SrtFormatError(
                f"{path}: block {ordinal} start is after end: {lines[1]!r}"
            )

        blocks.append(
            SrtBlock(
                ordinal=ordinal,
                index=index,
                start_ms=start_ms,
                end_ms=end_ms,
                start_text=start_text,
                end_text=end_text,
            )
        )

    return blocks


def compare_blocks(
    left_path: Path,
    right_path: Path,
    *,
    tolerance_ms: int,
    ignore_index: bool,
) -> AlignmentResult:
    left_blocks = parse_srt(left_path)
    right_blocks = parse_srt(right_path)
    mismatches: list[Mismatch] = []

    if len(left_blocks) != len(right_blocks):
        mismatches.append(
            Mismatch(
                ordinal=0,
                reason="block-count",
                left=str(len(left_blocks)),
                right=str(len(right_blocks)),
            )
        )

    for left, right in zip(left_blocks, right_blocks):
        if not ignore_index and left.index != right.index:
            mismatches.append(
                Mismatch(
                    ordinal=left.ordinal,
                    reason="index",
                    left=str(left.index),
                    right=str(right.index),
                )
            )

        start_delta = abs(left.start_ms - right.start_ms)
        if start_delta > tolerance_ms:
            mismatches.append(
                Mismatch(
                    ordinal=left.ordinal,
                    reason="start-time",
                    left=left.start_text,
                    right=right.start_text,
                    delta_ms=start_delta,
                )
            )

        end_delta = abs(left.end_ms - right.end_ms)
        if end_delta > tolerance_ms:
            mismatches.append(
                Mismatch(
                    ordinal=left.ordinal,
                    reason="end-time",
                    left=left.end_text,
                    right=right.end_text,
                    delta_ms=end_delta,
                )
            )

    return AlignmentResult(
        left_path=str(left_path),
        right_path=str(right_path),
        left_blocks=len(left_blocks),
        right_blocks=len(right_blocks),
        tolerance_ms=tolerance_ms,
        ignore_index=ignore_index,
        aligned=not mismatches,
        mismatches=mismatches,
    )


def print_human(result: AlignmentResult) -> None:
    print("SRT alignment check")
    print(f"left:  {result.left_path} ({result.left_blocks} blocks)")
    print(f"right: {result.right_path} ({result.right_blocks} blocks)")
    print(f"tolerance_ms: {result.tolerance_ms}")
    print(f"ignore_index: {str(result.ignore_index).lower()}")

    if result.aligned:
        print("status: aligned")
        return

    print("status: not aligned")
    print("mismatches:")
    for mismatch in result.mismatches:
        ordinal = "file" if mismatch.ordinal == 0 else f"block {mismatch.ordinal}"
        delta = "" if mismatch.delta_ms is None else f", delta={mismatch.delta_ms}ms"
        print(
            f"- {ordinal}: {mismatch.reason}: "
            f"left={mismatch.left!r}, right={mismatch.right!r}{delta}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check whether two SRT files have one-to-one matching block timing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
输出:
  默认输出人读摘要到 stdout；错误和非法输入输出到 stderr。
  使用 --json 时，stdout 只输出一个完整 JSON 文档。

Exit Codes:
  0  两个 SRT 时间轴对齐
  1  脚本运行成功，但发现 block 数量、编号或时间不一致
  2  参数错误或 SRT 格式错误
  4  文件读取失败

Examples:
  python scripts/check_srt_alignment.py zh-cn.srt en.srt
  python scripts/check_srt_alignment.py zh-cn.srt en.srt --tolerance-ms 50
  python scripts/check_srt_alignment.py zh-cn.srt en.srt --ignore-index --json
""",
    )
    parser.add_argument("left", type=Path, help="第一个 SRT 文件，例如原文字幕")
    parser.add_argument("right", type=Path, help="第二个 SRT 文件，例如译文字幕")
    parser.add_argument(
        "--tolerance-ms",
        type=int,
        default=0,
        help="允许的 start/end 时间误差，单位毫秒，默认 0",
    )
    parser.add_argument(
        "--ignore-index",
        action="store_true",
        help="只检查 block 数量和时间，不检查字幕编号是否一致",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读 JSON；stdout 不混入其他说明文字",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.tolerance_ms < 0:
        parser.error("--tolerance-ms must be >= 0")

    try:
        result = compare_blocks(
            args.left,
            args.right,
            tolerance_ms=args.tolerance_ms,
            ignore_index=args.ignore_index,
        )
    except SrtFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    if args.json:
        payload = asdict(result)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human(result)

    return 0 if result.aligned else 1


if __name__ == "__main__":
    raise SystemExit(main())
