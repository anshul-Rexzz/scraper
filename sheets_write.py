"""
Writes a Campus SP/SB/SD/Total reconciliation block (Amazon Console,
Hector Console, and a Variation % row) into the "Reconciliation-Auto
check" Google Sheet, in the same layout as the user's reference
"Reconciliation Check" sheet. Finds the next block's start row from the
sheet's own content, so repeated runs append rather than overwrite.

Variation % = (Amazon - Hector) * 100 / Amazon - written as a live Sheets
formula referencing the two data rows above it, not a pre-computed
number, so it stays correct if either row is ever hand-edited.
"""
from datetime import datetime

HEADER_ROW_OFFSET = 3  # rows below the block's first row for the Platforms/Orders/Revenue header
DATA_COLS = ["C", "D", "E", "F", "G", "H", "I", "J"]
BOLD = {"textFormat": {"bold": True}}
HEADER_SHADE = {"backgroundColor": {"red": 0.93, "green": 0.95, "blue": 0.99}, "textFormat": {"bold": True}}
ORDERS_FORMAT = {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}


def _revenue_format(currency_symbol: str) -> dict:
    return {"numberFormat": {"type": "CURRENCY", "pattern": f"{currency_symbol}#,##0.00"}}


def find_next_empty_row(ws, start_search: int = 1) -> int:
    """Google's API silently omits trailing blank rows from get_all_values(),
    so a gap left after the previous block can get "un-counted" and the
    next block ends up jammed directly against it (confirmed live). Column
    A carries an invisible single-space anchor in every spacer row (see
    write_campus_block) specifically so this scan can't lose track of it."""
    all_values = ws.get_all_values()
    row = len(all_values) + 1
    return max(row, start_search)


def add_variation_warning_format(ws, variation_row: int) -> None:
    """Conditional format: a Variation % cell turns red when its magnitude
    is >=5% in EITHER direction - a live Sheets rule tied to the formula's
    own output, so it re-evaluates automatically if the underlying Amazon/
    Hector numbers are ever edited, rather than a one-time static color."""
    ws.spreadsheet.batch_update({
        "requests": [{
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": ws.id,
                        "startRowIndex": variation_row - 1, "endRowIndex": variation_row,
                        "startColumnIndex": 2, "endColumnIndex": 10,  # C:J
                    }],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{"userEnteredValue": f"=ABS(C{variation_row})>=5"}],
                        },
                        "format": {
                            "backgroundColor": {"red": 0.91, "green": 0.2, "blue": 0.2},
                            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                        },
                    },
                },
                "index": 0,
            }
        }]
    })


def _ensure_column_widths(ws) -> None:
    ws.spreadsheet.batch_update({
        "requests": [{
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id, "dimension": "COLUMNS",
                    "startIndex": 1, "endIndex": 2,  # column B
                },
                "properties": {"pixelSize": 150},
                "fields": "pixelSize",
            }
        }]
    })


def write_campus_block(
    ws,
    start_row: int,
    from_date: str,
    to_date: str,
    amazon: dict | None,
    hector: dict,
    hector_mcp: dict | None = None,
    updated_by: str = "Automated",
    brand_display_name: str = "Campus",
    currency_symbol: str = "₹",
) -> int:
    """amazon/hector/hector_mcp dicts: {"sp": (orders, revenue), "sb": (...), "sd": (...), "total": (...)}
    hector_mcp is optional - the row is left blank (as before) if not given.
    amazon is also optional (e.g. a Hector-only scheduled run while Amazon
    login needs a human for 2FA) - its row and the Variation % row (which
    needs Amazon as the denominator) are both left blank, to be filled in
    by a later manual run once Amazon data is available.
    Returns the row number where the NEXT block should start."""
    now = datetime.now()
    r = start_row

    ws.update(f"B{r}", [[brand_display_name]])
    ws.update(f"D{r}", [[f"Updated by {updated_by}"]])
    ws.format(f"B{r}", BOLD)

    ws.update(f"B{r+1}", [[f"From :- {from_date} to {to_date}"]])
    ws.update(f"J{r+1}:M{r+1}", [[
        "Update date:-", now.strftime("%d %B"), "Time:-", now.strftime("%I.%M %p")
    ]])

    header_row = r + HEADER_ROW_OFFSET - 1
    ws.update(f"C{header_row}:J{header_row}", [["SP", "", "SB", "", "SD", "", "Total", ""]])
    ws.merge_cells(f"C{header_row}:D{header_row}")
    ws.merge_cells(f"E{header_row}:F{header_row}")
    ws.merge_cells(f"G{header_row}:H{header_row}")
    ws.merge_cells(f"I{header_row}:J{header_row}")
    ws.format(f"C{header_row}:J{header_row}", HEADER_SHADE)

    col_header_row = header_row + 1
    ws.update(f"B{col_header_row}:J{col_header_row}", [[
        "Platforms", "Orders", "Revenue", "Orders", "Revenue", "Orders", "Revenue", "Orders", "Revenue"
    ]])
    ws.format(f"B{col_header_row}:J{col_header_row}", HEADER_SHADE)

    def data_row(label: str, d: dict) -> list:
        return [
            label,
            d["sp"][0], d["sp"][1],
            d["sb"][0], d["sb"][1],
            d["sd"][0], d["sd"][1],
            d["total"][0], d["total"][1],
        ]

    amazon_row = col_header_row + 1
    hector_row = col_header_row + 2
    mcp_row = col_header_row + 3
    variation_row = col_header_row + 4
    if amazon is not None:
        ws.update(f"B{amazon_row}:J{amazon_row}", [data_row("Amazon Console", amazon)])
    else:
        ws.update(f"B{amazon_row}", [["Amazon Console"]])  # left blank - fill in later
    ws.update(f"B{hector_row}:J{hector_row}", [data_row("Hector Console", hector)])
    if hector_mcp is not None:
        ws.update(f"B{mcp_row}:J{mcp_row}", [data_row("Hector MCP", hector_mcp)])
    else:
        ws.update(f"B{mcp_row}", [["Hector MCP"]])  # left blank - fill in later
    ws.format(f"B{amazon_row}:B{hector_row}", BOLD)
    ws.format(f"B{mcp_row}", BOLD)

    # Orders columns as plain thousands-separated integers, Revenue
    # columns as rupee amounts - makes the block scannable instead of a
    # wall of undifferentiated digits.
    last_data_row = mcp_row if hector_mcp is not None else hector_row
    for col in ("C", "E", "G", "I"):
        ws.format(f"{col}{amazon_row}:{col}{last_data_row}", ORDERS_FORMAT)
    for col in ("D", "F", "H", "J"):
        ws.format(f"{col}{amazon_row}:{col}{last_data_row}", _revenue_format(currency_symbol))

    if amazon is not None:
        # Variation (%) = (Amazon - Hector) * 100 / Amazon, per the user's
        # formula - one live formula per column, always relative to Amazon.
        # Referencing amazon_row here is why this whole row is skipped
        # when amazon is None - with no Amazon numbers the formula would
        # just divide by a blank cell and show an error instead of a
        # number, so leave it for a later run to fill in once Amazon data
        # exists for this block.
        variation_formulas = [
            f"=({col}{amazon_row}-{col}{hector_row})*100/{col}{amazon_row}" for col in DATA_COLS
        ]
        ws.update(
            f"B{variation_row}:J{variation_row}",
            [["Variation %"] + variation_formulas],
            value_input_option="USER_ENTERED",
        )
        ws.format(f"C{variation_row}:J{variation_row}", {"numberFormat": {"type": "NUMBER", "pattern": "0.00\"%\""}})
        add_variation_warning_format(ws, variation_row)
    else:
        ws.update(f"B{variation_row}", [["Variation %"]])
    ws.format(f"B{variation_row}", BOLD)

    # Anchor the 2 blank spacer rows (see find_next_empty_row docstring) -
    # an invisible single space in column A, well clear of any visible
    # column, so the gap survives into the next run's row-scan.
    ws.update(f"A{variation_row+1}", [[" "]])
    ws.update(f"A{variation_row+2}", [[" "]])

    return variation_row + 3  # leave 2 blank rows before the next block
