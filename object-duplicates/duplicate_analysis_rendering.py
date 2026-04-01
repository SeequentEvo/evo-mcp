from __future__ import annotations

from html import escape
from typing import Any

import ipywidgets as widgets
from IPython.display import display


def _parse_pct(value: str) -> float:
    return float(value.rstrip("%")) if value.endswith("%") else float(value)


def _overlap_heat_color(overlap_pct: float) -> str:
    normalized = max(0.0, min(overlap_pct / 100.0, 1.0))
    hue = 18 + (normalized * 92)
    saturation = 44
    lightness = 97 - (normalized * 24)
    return f"hsl({hue:.0f}, {saturation}%, {lightness:.0f}%)"


def _text_color_for_overlap(overlap_pct: float) -> str:
    return "#FFFFFF" if overlap_pct >= 88 else "#101828"


def _pair_cards_html(rows: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for row in rows:
        overlap_pct = _parse_pct(str(row["Blob Overlap %"]))
        heat_background = _overlap_heat_color(overlap_pct)
        heat_text = _text_color_for_overlap(overlap_pct)
        cards.append(
            "<div style='border:1px solid #D8DDE6;border-radius:14px;padding:10px;background:#FFFFFF;'>"
            "<div style='display:grid;grid-template-columns:minmax(0,1fr) minmax(160px,190px) minmax(0,1fr);gap:8px;align-items:stretch;'>"
            f"{_object_card_html('Object 1', '#E7F0FF', '#163B68', row['Object 1 Name'], row['Object 1 Workspace'], row['Object 1 Schema'], row['Object 1 Blobs'], row['Object 1 Created By'], row['Object 1 Created At'])}"
            f"{_comparison_card_html(row['Shared Blobs'], row['Blob Overlap %'], heat_background, heat_text)}"
            f"{_object_card_html('Object 2', '#FFF1E6', '#8A3B12', row['Object 2 Name'], row['Object 2 Workspace'], row['Object 2 Schema'], row['Object 2 Blobs'], row['Object 2 Created By'], row['Object 2 Created At'])}"
            "</div>"
            "</div>"
        )

    return (
        "<div style='display:flex;flex-direction:column;gap:8px;width:100%;'>"
        + "".join(cards)
        + "</div>"
    )


def _object_card_html(
    label: str,
    accent_background: str,
    accent_text: str,
    name: Any,
    workspace: Any,
    object_schema: Any,
    blob_count: Any,
    created_by: Any,
    created_at: Any,
) -> str:
    return (
        "<div style='border:1px solid #D8DDE6;border-radius:12px;padding:9px;background:#FCFCFD;min-width:0;'>"
        f"<div style='display:inline-flex;align-items:center;padding:3px 7px;border-radius:999px;background:{accent_background};color:{accent_text};font-size:10px;font-weight:700;margin-bottom:8px;'>{escape(str(label))}</div>"
        f"<div style='font-size:14px;font-weight:700;color:#101828;margin-bottom:8px;overflow-wrap:anywhere;word-break:break-word;'>{escape(str(name))}</div>"
        "<div style='display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:8px;'>"
        f"{_metric_tile_html('Workspace', workspace, '#F8FAFC')}"
        f"{_metric_tile_html('Schema', object_schema, '#F8FAFC')}"
        f"{_metric_tile_html('Created by', created_by, '#F8FAFC')}"
        f"{_metric_tile_html('Created', created_at, '#F8FAFC')}"
        f"{_metric_tile_html('Blobs', blob_count, '#F8FAFC')}"
        "</div>"
        "</div>"
    )


def _comparison_card_html(shared_blobs: Any, overlap_pct: Any, heat_background: str, heat_text: str) -> str:
    return (
        "<div style='border:1px solid #D8DDE6;border-radius:12px;padding:9px;background:#F8FAFC;display:flex;flex-direction:column;justify-content:center;gap:8px;min-width:0;'>"
        "<div style='font-size:10px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;color:#475467;'>Comparison</div>"
        f"<div style='border-radius:10px;padding:10px;background:{heat_background};color:{heat_text};'>"
        "<div style='font-size:10px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;opacity:0.9;'>Blob Overlap</div>"
        f"<div style='font-size:24px;line-height:1.05;font-weight:800;margin-top:3px;'>{escape(str(overlap_pct))}</div>"
        "</div>"
        f"{_metric_tile_html('Shared Blobs', shared_blobs, '#FFFFFF')}"
        "</div>"
    )


def _metric_tile_html(label: str, value: Any, background: str) -> str:
    return (
        f"<div style='border-radius:8px;padding:8px;background:{background};min-width:0;'>"
        f"<div style='font-size:10px;color:#5F6B7A;font-weight:600;margin-bottom:3px;'>{escape(str(label))}</div>"
        f"<div style='font-size:13px;color:#101828;font-weight:700;overflow-wrap:anywhere;word-break:break-word;'>{escape(str(value))}</div>"
        "</div>"
    )


def _render_text_table(rows: list[dict[str, Any]]) -> None:
    headers = [
        "Object 1 Workspace",
        "Object 1 Name",
        "Object 1 Schema",
        "Object 1 Blobs",
        "Object 1 Created By",
        "Object 1 Created At",
        "Object 2 Workspace",
        "Object 2 Name",
        "Object 2 Schema",
        "Object 2 Blobs",
        "Object 2 Created By",
        "Object 2 Created At",
        "Shared Blobs",
        "Blob Overlap %",
    ]
    widths = {header: len(header) for header in headers}
    for row in rows:
        for header in headers:
            widths[header] = max(widths[header], len(str(row[header])))

    def line(char: str = "-") -> str:
        return "+" + "+".join(char * (widths[header] + 2) for header in headers) + "+"

    print(line("="))
    print("| " + " | ".join(header.ljust(widths[header]) for header in headers) + " |")
    print(line("="))
    for row in rows:
        print("| " + " | ".join(str(row[header]).ljust(widths[header]) for header in headers) + " |")
    print(line("-"))


def _summary_card(label: str, value: str) -> str:
    return (
        "<div style='border:1px solid #D8DDE6;border-radius:10px;padding:10px 12px;min-width:120px;'>"
        f"<div style='color:#5F6B7A;font-size:12px;margin-bottom:4px;'>{escape(label)}</div>"
        f"<div style='color:#101828;font-size:18px;font-weight:600;'>{escape(value)}</div>"
        "</div>"
    )


def render_analysis_result(result: Any) -> None:
    print(f"Workspaces scanned: {result.workspaces_scanned}")
    print(f"Objects scanned: {result.objects_scanned}")
    print(f"Comparable objects: {result.objects_with_blob_refs}")
    print(f"Objects with no blobs: {result.objects_without_blob_refs}")
    print(f"Objects with fetch errors: {result.objects_with_fetch_errors}")
    print(f"Unique blob hashes: {result.unique_blob_hashes}")
    print(f"Duplicate blob hashes: {result.duplicate_blob_hash_count}")
    print(f"Object pairs with duplicated blobs: {len(result.object_pair_duplicate_counts)}")

    if result.rows:
        print("\nObject duplicate summary:")
        try:
            display(result.to_dataframe())
        except Exception:
            _render_text_table(result.sorted_rows())
    else:
        print("\nNo object pairs with duplicated blob hashes found.")


def build_analysis_result_widget(result: Any) -> widgets.Widget:
    summary_cards = widgets.HTML(
        "<div style='display:flex;flex-wrap:wrap;gap:10px;'>"
        + _summary_card("Objects scanned", str(result.objects_scanned))
        + _summary_card("Comparable objects", str(result.objects_with_blob_refs))
        + _summary_card("No blobs", str(result.objects_without_blob_refs))
        + _summary_card("Fetch errors", str(result.objects_with_fetch_errors))
        + _summary_card("Unique blob hashes", str(result.unique_blob_hashes))
        + _summary_card("Duplicate object pairs", str(len(result.object_pair_duplicate_counts)))
        + "</div>"
    )

    if result.rows:
        title = widgets.HTML("<b>Object duplicate summary</b>")
        table = widgets.HTML(_pair_cards_html(result.sorted_rows()))
        table_box = widgets.Box(
            [table],
            layout=widgets.Layout(
                border="1px solid #D8DDE6",
                border_radius="10px",
                display="block",
                width="100%",
            ),
        )
        return widgets.VBox([summary_cards, title, table_box], layout=widgets.Layout(gap="10px", width="100%"))

    empty_state = widgets.HTML(
        "<div style='border:1px solid #D8DDE6;border-radius:10px;padding:14px;color:#5F6B7A;'>"
        "No object pairs with duplicated blob hashes found."
        "</div>"
    )
    return widgets.VBox([summary_cards, empty_state], layout=widgets.Layout(gap="10px", width="100%"))