# 複数行見出しの明示マッピング：レビュー専用試験版（2026-11-08）

## 何を解決するか

リードオフジャパン等の価格表は、商品コード・商品名/POS/ITF・入数・価格が複数行の見出しに分散する。従来は`header_layout_guard`により`multi_row_needs_review`として全行の抽出を保留していた。**根拠のある独立した見出し項目だけを人が指定した場合に限り、商品検索の候補を得る**ためのオフライン機能を開発ブランチに追加した。

- [`tiered_header_mapping.py`](tiered_header_mapping.py)で指定見出しの**物理行番号・列番号と実セルの見出しラベルが完全に対応すること**を検証。
- [`multi_source_readonly.py`](multi_source_readonly.py)へ統合して、`mapped_review`という**「明示された項目を候補として一部抽出したが、商品・仕入条件は未確定」**のステータスで返す。
- [`sheets_multi_bridge.py`](sheets_multi_bridge.py)と[`local_excel_bridge.py`](local_excel_bridge.py)の**両方**がマニフェスト内の`tiered_mapping`を受け付ける。**形式不正はGoogle APIやローカルExcelへのアクセスより先に拒否**。
- データ入力は**承認済みの最大5資料・各A1:O40**に限る。外部I/O、価格計算、発注、JAN正本選択、PDF解析は行わない。

## 架空の2段/3段見出し例

これは**実取引先の価格表ではない**。パスや識別子も架空である。

```python
from supplier_docs.multi_source_readonly import (
    normalize_selected_sources, search_selected_sources,
)

rows = [
    [],
    ['商品名', '', ''],
    ['', 'JAN', ''],
    ['', '', '価格'],              # 価格の意味/税/単位が不明
    ['架空マスク', '0000000000017', 999],
]
spec = {
    'source_file_id': 'FAKE_SOURCE_0001',
    'source_sheet': '架空の階層見出し',
    'document_type': 'quote_response',
    'rows': rows,
    'tiered_mapping': {
        'version': 'tiered-review-v1',
        'header_rows': [2, 3, 4],
        'data_start_row': 5,
        'fields': {
            'product_name_raw': {'row': 2, 'column': 1},
            'jan_string': {'row': 3, 'column': 2},
        },
    },
}
normalized = normalize_selected_sources([spec])
assert normalized['public_summary']['source_status_counts']['mapped_review'] == 1
assert normalized['public_summary']['records_with_cost_field'] == 0
assert normalized['public_summary']['profit_calculation_allowed'] is False
lookup = search_selected_sources(
    normalized, field='jan', query='0000000000017')
assert lookup['public_summary']['hits_returned'] == 1
assert lookup['public_summary']['product_identity_confirmed'] is False
# 商品名・JAN/ASIN・元の行番号・根拠見出し座標はPRIVATE返値のみ。
```

マニフェストの`header_rows`は2～4行、`data_start_row`はその後・最大40行、`fields`は別々の列にある明示的な見出しに限定する。**同じセルや列を商品名とJANの両方として扱えない**。

## 自動で行わない処理と保留理由

- マッピング可能な候補フィールドは`product_name_raw`、`jan_string`、`asin`、`model_number`、`manufacturer_name_raw`だけ。**`cost_amount`、`order_multiple`、税区分、ケース入数、利益区分は指定しても拒否**する。
- 実際の選択見出しセルが対応する独立ラベル（例：`JAN`）と**完全一致しなければ、レコードを作らない**。`商品名・POSコード・ITFコード`など**複数識別子が一つの見出しに含まれる場合は商品名やJANに自動で変換しない**。
- このため、既に構造確認した**リードオフジャパン実資料の2シートは、現時点でも`multi_row_needs_review`のまま**である。元の各列が本当に独立したJAN/商品名/価格を表すと確認できるまで、マニフェストを作って無理に解釈しない。
- マッピングが成立しても`mapped_review`であり、`all_selected_windows_parsed=false`。各候補の`decision=needs_confirmation`、`cost_present=false`、`cost_tax_mode=unknown`。JAN/ASINの完全一致は**候補検索が動いた**ことを示すだけで、同一商品の証明にならない。
- **価格や原本の未確認欄を自動補完する機能ではない**。Google Drive元ファイルの読取権限・最新の見積条件・Amazon販売セット数は別途確認が必要。

## テストと実運用の線引き

- [13件の架空データによるスキーマ／商品候補／POS-ITF拒否／機密保護テスト](../tests/test_supplier_tiered_header_mapping.py)。
- [4件の架空Google SheetsとExcelブリッジへの結合テスト](../tests/test_supplier_tiered_bridges.py)。**無効なGoogle SheetsマッピングはAPI呼び出し前に拒否**し、Excelも元ファイルを変更しない。
- 実Google Drive原本の新しい多段明示マッピングは**未実施**。以前の[実Excel E2E](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/pilots/four-supplier-real-excel-e2e-2026-11-08.md)では、階層見出しの2タブを正しく`needs_review`として保留することを確認した。今回の実装は**その安全な保留状態を壊さず、明確な個別見出しがある資料で段階的に検索候補を抽出する機能**である。
- 実JAN・ASIN・原価・ファイル名・対応マニフェストは公開CIやGitHubへ保存しない。開発用**Draft PR #1は未マージ**、本番IAM/WIF/SP-API/Keepa変更や追加費用なし。

