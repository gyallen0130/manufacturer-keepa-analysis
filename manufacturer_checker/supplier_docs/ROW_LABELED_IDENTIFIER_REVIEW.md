# 行ごとに「POSコード」「ITFコード」を持つ多段価格表の安全な検索候補抽出

2026-11-08実装。目的は**Excel・Google Sheetsに共通して、元の行・列に紐づくPOS/ITF識別番号の検索候補を得る**ことであり、POSとJANを同一視したり、仕入利益や販売SKUを確定したりすることではない。

## 適用できる原本形式

リードオフジャパンの一部価格表では、ヘッダーが12～15行目の複数段に分かれる一方、商品行に**別のセルとして「POSコード：」と「ITFコード：」というラベルがあり、その隣のセルに番号候補がある**。通常の`tiered_header_mapping.py`は「商品名・POSコード・ITFコード」という**複合見出し**を単独JAN見出しとして認めない。そこで、**原本の商品行のラベル／値ペアのみ**を別経路で抽出する。

共通[`row_labeled_candidates.py`](row_labeled_candidates.py)の入力は、事前承認された**A1:O40以内**の行列と、人が確認して指定した列番号。**元行の識別子と値の組み合わせ・原本ファイル名・JAN/ASIN等はすべてPRIVATE**で扱う。

架空例：

```python
from supplier_docs.multi_source_readonly import (
    normalize_selected_sources, search_selected_sources,
)

fake_rows = [[] for _ in range(17)]
fake_rows[11] = ['', '商品コード']
fake_rows[12] = ['', '', '', '', '商品名・POSコード・ITFコード']
fake_rows[13] = ['', '', '', '', '', '', '', '入数', '', '', '価格']
fake_rows[14] = ['', '', '', '', '', '', '', '', '', '', '価格']
fake_rows[16] = ['', '', '', 'POSコード：', '0000000000017',
                 'ITFコード：', '10000000000007']
spec = [{
    'source_file_id': 'FAKE_PRIVATE_VENDOR_001',
    'source_sheet': '架空の階層価格表',
    'document_type': 'catalog',
    'rows': fake_rows,
    'row_labeled_mapping': {
        'version': 'row-label-review-v1',
        'data_start_row': 16,
        'fields': {
            'pos_candidate': {'label_column': 4, 'value_column': 5},
            'itf_candidate': {'label_column': 6, 'value_column': 7},
        },
    },
}]
result = normalize_selected_sources(spec)
assert result['public_summary']['source_status_counts']['labeled_review'] == 1
assert result['public_summary']['records_with_jan'] == 0
assert result['public_summary']['records_with_pos_candidate'] == 1
assert result['public_summary']['profit_calculation_allowed'] is False
hit = search_selected_sources(result, field='pos', query='0000000000017')
assert hit['public_summary']['hits_returned'] == 1
# 'jan' で同じ番号を探しても「確定JAN」へは昇格しない。
assert search_selected_sources(result, field='jan', query='0000000000017')[
    'public_summary']['hits_returned'] == 0
```

## マッピングの安全性

- **マニフェストの指定されたPOS/ITFラベルと、その右隣のセルだけ**を読む。異なるラベル・不明列を推測でJANに変換しない。
- POS候補は8/12/13桁、ITF候補は14桁の**数字文字列**だけを受け、GS1チェックデジットが一致するか形式検査する。ただし**チェックデジット一致は実商品・JAN・取引可否の証明ではない**。
- **数値セルは先頭0を失った可能性があるので候補へ採用しない**。数式、空欄、`-`、形式不明も未採用。警告はコードのみで、実値を出さない。
- 商品名、ブランド、SKU、価格、入数、税区分は抽出しない。各候補は`decision='needs_confirmation'`、`cost_present=False`、`jan_string=''`、`product_name_raw=''`で、**独立した商品コード候補のまま**。
- POS候補は`search_selected_sources(...,field='pos',...)`、ITFは`field='itf'`の**完全一致検索**を使う。従来のJAN検索へ自動合流しない。結果に元の物理行を含むが、それはPRIVATEで保持する。
- **1～5ソースのみ**の手動限定検索。検索先の資料が`labeled_review`だけでJANを検索した場合、`sources_without_field_coverage`に未確認資料が計上される。検索0件＝112社に存在しない、ではない。
- **`row_labeled_mapping`と`tiered_mapping`を同時指定できない**。不正な入力はSheetsのAPI呼出し前、Excelファイルへのアクセス前に拒否する。

## 実資料の確認とテストの区別

同日、許可されたローカルの実Excelで、リードオフジャパンの**2つのシート各A1:O40**を限定確認した。商品行に独立したPOS/ITFラベルがあることを確認し、**文字列型のチェックデジット整合POS候補6件・ITF候補1件**、**数値型のため保留する番号3件**を匿名集計した。数式や価格は計算・転載していない。実商品と原本行はGitHubへ保存しない。

この実データ確認は**ローカルの独立した構造検査**であり、**新しい`row_labeled_candidates.py`を実Excelで動かした最終E2Eではない**。新プログラムは架空データの[14テスト](../tests/test_supplier_row_labeled_candidates.py)と、Sheets/Excelの[6接続テスト](../tests/test_supplier_row_labeled_bridges.py)で検証する。

**次の共通化課題**：この共通関数を実Excelで許可済みA1:O40のまま動かし、異なる卸の通常JANとPOS候補を**別の項目として並べて検索**する。ただし正式なメーカー・Amazonの商品同一性や価格・仕入単位の確認までは、`needs_confirmation`を維持する。

ChatGPT先行・Claude将来互換、追加有料サービス・IAM変更・自動巡回・本番SP-API/発注なし。コードはDraft PR #1内、未マージ。

