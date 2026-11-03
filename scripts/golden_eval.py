"""模組名稱：scripts.golden_eval
功能說明：黃金測試集評分與（選用）對真實 API 的辨識執行：欄位級 Exact Match、錯誤攔截率、整張通過率。
使用方式：
    評分（離線，不連任何服務）：把 /recognize 的回應存成 JSON 後呼叫 score_invoice／summarize。
    執行（會呼叫真實 API，有成本與副作用）：
        python -m scripts.golden_eval run --api-base http://127.0.0.1:8000 --token-file <檔案> \\
            --images-dir <正確發票資料夾> --manifest tests/golden/manifest.json --limit 10 --yes-write
注意事項：
    - 真實執行會對該 API 所連的 DB／Storage 寫入辨識紀錄與影像（本機 API 連的是正式環境）；必須明確帶 --yes-write。
    - Token 只從 --token-file 讀取，不放在命令列或程式；報告不寫入 Token、影像或完整回應。
    - 真實發票影像不得放入 Git；manifest 只含檔名與人工標註值（虛構資料）。
    - 只有標了 annotated 的發票才計欄位正確率；其餘只比對檔名的字軌號碼。
"""

import argparse
import json
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.utils.invoice_format import chinese_amount_to_int

HEADER_FIELDS = (
    "invoice_track",
    "invoice_number",
    "invoice_date",
    "buyer_tax_id",
    "buyer_name",
    "seller_tax_id",
    "seller_name",
    "tax_type",
    "sales_amount",
    "tax_amount",
    "total_amount",
)
NUMBER_FIELDS = frozenset({"sales_amount", "tax_amount", "total_amount"})
ITEM_FIELDS = ("item_name", "quantity", "unit_price", "line_amount")
# 警示的 field 對應到哪些欄位算「已被攔截」
WARNING_COVERS = {
    "total_amount": ("total_amount", "total_amount_zh"),
    "sales_amount": ("sales_amount", "items"),
    "tax_amount": ("tax_amount", "tax_type"),
}


@dataclass
class FieldResult:
    """單一欄位的比對結果。"""

    name: str
    expected: Any
    actual: Any
    correct: bool
    intercepted: bool  # 錯誤時：值為空（需人工填）或有警示指到該欄位


@dataclass
class InvoiceScore:
    """單張發票的評分。"""

    name: str
    fields: list[FieldResult] = field(default_factory=list)

    @property
    def all_correct(self) -> bool:
        return all(item.correct for item in self.fields)

    @property
    def wrong_uncaught(self) -> list[str]:
        """錯了而且沒有被攔截的欄位——這是最危險的一類（使用者可能直接信任）。"""
        return [item.name for item in self.fields if not item.correct and not item.intercepted]


def _same(name: str, expected: Any, actual: Any) -> bool:
    if expected is None:
        return actual is None
    if actual is None:
        return False
    if name in NUMBER_FIELDS or name in ("quantity", "unit_price", "line_amount"):
        try:
            return Decimal(str(expected)) == Decimal(str(actual))
        except InvalidOperation:
            return False
    return str(expected).strip() == str(actual).strip()


def _warned(warnings: Sequence[Mapping[str, Any]], names: Sequence[str]) -> bool:
    return any(
        w.get("field") in names
        or (str(w.get("field", "")).startswith("items.") and "items" in names)
        for w in warnings
    )


def score_invoice(
    name: str, expected: Mapping[str, Any], recognition: Mapping[str, Any]
) -> InvoiceScore:
    """依人工標註的 expected 評分一次 /recognize 回應。expected 只列要計分的欄位，沒列的不比。"""
    invoice = recognition.get("invoice") or {}
    warnings = recognition.get("warnings") or []
    score = InvoiceScore(name)

    def add(label: str, exp: Any, act: Any, covers: Sequence[str]) -> None:
        correct = _same(label, exp, act)
        intercepted = (not correct) and (act in (None, "") or _warned(warnings, covers))
        score.fields.append(FieldResult(label, exp, act, correct, intercepted))

    for key in HEADER_FIELDS:
        if key in expected:
            add(key, expected[key], invoice.get(key), WARNING_COVERS.get(key, (key,)))
    if "total_amount_zh" in expected:
        zh_value = chinese_amount_to_int(invoice.get("total_amount_zh"))
        exp_zh = expected["total_amount_zh"]
        actual_number = str(zh_value) if zh_value is not None else None
        add(
            "total_amount_zh",
            str(exp_zh) if exp_zh is not None else None,
            actual_number,
            ("total_amount_zh",),
        )
    exp_items = expected.get("items")
    if exp_items is not None:
        act_items = invoice.get("items") or []
        add("items.count", len(exp_items), len(act_items), ("items",))
        for index, exp_item in enumerate(exp_items):
            act_item = act_items[index] if index < len(act_items) else {}
            for key in ITEM_FIELDS:
                if key in exp_item:
                    add(
                        f"items.{index}.{key}",
                        exp_item[key],
                        act_item.get(key),
                        (f"items.{index}.{key}", f"items.{index}.line_amount", "items"),
                    )
    return score


def summarize(scores: Sequence[InvoiceScore]) -> dict[str, Any]:
    """彙總：欄位類別的 Exact Match、錯誤攔截率、整張全對率與未攔截的錯誤清單。"""
    by_field: dict[str, list[FieldResult]] = {}
    for score in scores:
        for item in score.fields:
            key = (
                item.name
                if not item.name.startswith("items.")
                else "items." + item.name.split(".")[-1]
            )
            by_field.setdefault(key, []).append(item)
    fields = {
        key: {
            "n": len(items),
            "exact_match": sum(i.correct for i in items) / len(items),
        }
        for key, items in sorted(by_field.items())
    }
    all_items = [i for items in by_field.values() for i in items]
    wrong = [i for i in all_items if not i.correct]
    return {
        "invoices": len(scores),
        "invoices_all_correct": sum(s.all_correct for s in scores),
        "fields_total": len(all_items),
        "fields_exact_match": (sum(i.correct for i in all_items) / len(all_items))
        if all_items
        else None,
        "wrong_fields": len(wrong),
        "interception_rate": (sum(i.intercepted for i in wrong) / len(wrong)) if wrong else None,
        "by_field": fields,
        "wrong_uncaught": {s.name: s.wrong_uncaught for s in scores if s.wrong_uncaught},
    }


def track_number_from_filename(filename: str) -> tuple[str, str] | None:
    """invoice_0100_RT39560800.jpg → ('RT', '39560800')；檔名帶 XX 等無法判讀的標記回 None。"""
    stem = Path(filename).stem.split("_")[-1]
    if len(stem) == 10 and stem[:2].isalpha() and stem[2:].isdigit():
        return stem[:2].upper(), stem[2:]
    return None


def load_manifest(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data["invoices"])


def _run(args: argparse.Namespace) -> int:
    import httpx  # 只有真實執行才需要

    if not args.yes_write:
        print("拒絕執行：會對 API 所連的 DB／Storage 寫入辨識紀錄與影像，請明確帶 --yes-write。")
        return 2
    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    entries = [e for e in load_manifest(Path(args.manifest)) if e.get("folder") == "correct"]
    if args.annotated_only:
        entries = [e for e in entries if e.get("annotated")]
    entries = entries[: args.limit]
    scores: list[InvoiceScore] = []
    for entry in entries:
        image = Path(args.images_dir) / entry["file"]
        if not image.is_file():
            print(f"略過（找不到檔案）：{entry['file']}")
            continue
        with httpx.Client(base_url=args.api_base, timeout=60.0) as client:
            response = client.post(
                "/api/v1/invoices/recognize",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": (image.name, image.read_bytes(), "image/jpeg")},
            )
        if response.status_code != 200:
            print(f"{entry['file']}: HTTP {response.status_code}")
            continue
        expected = dict(entry.get("expected") or {})
        scores.append(score_invoice(entry["file"], expected, response.json()))
        time.sleep(args.pause)
    report = summarize(scores)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="黃金測試集：對 API 辨識並評分")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="對真實 API 執行（有成本與副作用）")
    run.add_argument("--api-base", required=True)
    run.add_argument("--token-file", required=True)
    run.add_argument("--images-dir", required=True)
    run.add_argument("--manifest", default="tests/golden/manifest.json")
    run.add_argument("--limit", type=int, default=10)
    run.add_argument("--annotated-only", action="store_true")
    run.add_argument("--pause", type=float, default=2.0)
    run.add_argument("--report")
    run.add_argument("--yes-write", action="store_true")
    args = parser.parse_args(argv)
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
