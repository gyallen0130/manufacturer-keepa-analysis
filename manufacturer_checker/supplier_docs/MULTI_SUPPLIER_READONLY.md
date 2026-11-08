# 卸問屋横断の共通正規化・照会MVP（2026-11-08／開発用）

## 目的

今後の最優先方針は、**特定1社の見積価格を繰り返し調べることではなく、3〜5社の異なる資料から共通項目を抽出し、候補商品と原本へ戻れること**。開発コード[ `multi_source_readonly.py` ](multi_source_readonly.py)で既存の`parser.parse_rows`を一度に最大5資料へ適用し、結果を非公開の明細と公開安全な件数へ分離する。

**これは既存Google Drive/SheetsのAPIを直接呼ぶプログラムではない。** ChatGPTや許可されたプライベート実行環境が、既に読み取った**1～5個の限定行範囲**を渡したときだけ解析する。Driveを勝手に全巡回せず、GCP/GitHub Actions等の追加課金や認証変更は不要。

## 2026-11-08に実際の見出しを確認した4社

原本の必要な先頭部分だけを接続済みGoogle Driveで閲覧。以下は **列見出しに関する実測**であって、このPythonの実資料実行結果ではない。商品行・JAN/ASIN・価格は本ドキュメントに記録しない。

| 取引先と検査タブ | 先頭20行内の主な列見出し | 共通項目上の注意 |
| --- | --- | --- |
| [株式会社井上／「見積もり」](https://docs.google.com/spreadsheets/d/1qakllf_kkwnpzrOIIRs-oqLiffINjVUa4fIRT0gnl5U/edit) | 1行目：メーカー／商品名／商品名（Amazon）／JAN／品番／上代(税抜）／発注単位／下代(税抜） | `品番`を`model_number`、下代税抜を`cost_tax_mode='excluded'`へ。上代（希望小売価格相当）を仕入コストとして扱わない |
| [ワコーフーズ／「新田ゼラチン」](https://docs.google.com/spreadsheets/d/1MxnvUDWz7JWj5_dKtxN9iYiOOZUcTfhd7G4H_yRmke8/edit) | 1行目：商品名／商品名（Amazon）／ASIN／JAN／発注単位／卸値（税込） | `卸値（税込）`は税込のコスト列。ただしメーカー名のタブは**原本の行のメーカー名を証明しない**。タブ名だけで`manufacturer_name_raw`を埋めない |
| [ヨシダ／「GEX」](https://docs.google.com/spreadsheets/d/1i1VZUViLNK9WCUOwH3g7rbubfPGr0GfC6M8eleLh0RM/edit) | 1行目：メーカー／商品名／商品名（Amazon）／ASIN／JAN／発注単位（ケース/カートン）／BOX入り数×ケース内ボックス数／卸価格／税込仕入れ値 | 価格列が複数で**内容や単位が異なる**。今の安全な共通パーサーでは両者の価格を単純に1つの`cost_amount`へ選ばず、要確認とする |
| [株式会社イトウ／「シート1」](https://docs.google.com/spreadsheets/d/1kLd8GVwYp0rzwKRM_8t9rp5RRGyCJuHqxifxb1D8naQ/edit) | 3行目：商品名／JAN／ASIN | 見出し行が3行目のため1行目を固定ヘッダーとしない。見積依頼側のSheetsと返信Excelは別の原本であり、無条件に同じ価格表としてマージしない |

## 共通正規化処理

```python
from supplier_docs.multi_source_readonly import (
    normalize_selected_sources, search_selected_sources,
)

# 以下はダミーID・架空JAN/商品である。
samples = [
    {
        'source_file_id': 'DEMO_SOURCE_001',
        'source_sheet': 'シート1',
        'source_url': 'https://example.invalid/sheet',
        'document_type': 'quote_request',
        'rows': [
            ['商品名', 'JAN', 'ASIN'],
            ['架空マスク', '0000000000017', 'B0TEST0001'],
        ],
    },
]
result = normalize_selected_sources(samples)
# 出してよいのは件数等の集計だけ。
print(result['public_summary'])
# JANは完全一致、商品名は正規化した部分一致。
hits = search_selected_sources(
    result, field='jan', query='0000000000017')
print(hits['public_summary'])

# 次は元Driveと照合する必要のあるPRIVATE参照。公開しない。
private_docs = result['private_normalized_docs']
private_hits = hits['private_hits']
```

- 受入形式：`document_type`を明示した1～5資料。資料ごと1～200物理行、1行40列以内。商品候補が記録にない場合は未照合範囲を別途記載する。
- **`public_summary`に実JAN、ASIN、商品名、原本ID、実原価は含めない**。行数・抽出件数・既知フィールドの被覆率・警告件数だけ。
- `private_normalized_docs`には各資料の`source_url / source_sheet / source_row / mapped_columns`と商品別JAN/ASIN等が含まれる。**許可された非公開の一時処理だけ**で使用し、Private GitHub索引にも詳細行を複写しない。
- `search_selected_sources`は**あらかじめ読み込んだ1～5資料のローカル検索のみ**。JANとASINは厳格な完全一致。商品名・メーカー名・型番は正規化した部分一致。検索ヒットは原本の行番号まで戻せるが、同一SKU、仕入可、現在の販売単位、見積有効性は確定しない。
- `mapped_source_counts`は、何社でその列見出しが共通項目に写像されたかの件数。**該当値が完全で正しいという意味ではない**。税区分が不明・価格列が曖昧なら安全側で未確定にする。
- **画像PDFはまだ処理対象外**。Excelは原本を別途適切に読み取って2次元行配列として渡せるが、このモジュールそのものはExcel/Google SheetsのファイルI/Oをしない。

## Google Sheetsへの読取専用接続を行う新しい境界

2026-11-08、[sheets_multi_bridge.py](sheets_multi_bridge.py)を追加した。利用者／権限のあるPRIVATE実行環境で**すでに認証済みのGoogle Sheets v4読取専用クライアント**を受け取り、明示的に選んだ**1〜5タブ**について、他の情報を自動発見せず**メタデータでタブを検証→A1:O40をFORMULA形式で読取→上記`normalize_selected_sources`へ渡す**。

```python
from supplier_docs.sheets_multi_bridge import (
    SCHEMA_VERSION, inspect_selected_google_sheets,
)

# これは架空のIDと商品を使う構造例です。
approved_private = {
    'schema_version': SCHEMA_VERSION,
    'mode': 'manual_readonly',
    'targets': [{
        'spreadsheet_id': 'FAKE_PRIVATE_SHEET_001',
        'title': 'シート1',
        'document_type': 'quote_request',
    }],
}
# client は別途ユーザーが読取専用の権限で認証済みのSheets v4。
# review = inspect_selected_google_sheets(client, manifest=approved_private)
# print(review['public_summary'])  # 集計件数のみ
# review['private_normalized_docs'] は機密行を含むので公開しない。
```

- **外部呼出し前に全選択を検証**：許可されたスキーマ、最大5件、指定タブ名、ドキュメント種別、任意の見出し行、文字長。全タブの可視性をメタデータで確認してから商品行を読む。最大3000セル（5×40×15）。検索条件が無効／短すぎれば**APIに触れず拒否**する。
- **原本の型を保持**：Google Sheets APIの`valueRenderOption=FORMULA`で、数値型JANと式を文字列の見た目に変換しない。パーサーは数式を評価せず、JANの先頭0の補完もせず、矛盾時は要確認にする。
- **公開安全な結果**：`public_summary`は資料件数・抽出件数・警告件数・曖昧な共通フィールド（例：2列とも価格候補）・読取API呼出し件数・式セル件数のみ。**生JAN/ASIN/原価/商品名/ファイルIDは返さない**。個別行は`private_normalized_docs`、検索ヒットは`private_hits`に留める。
- 読取専用とは**認証/接続権限の代替ではない**。このコードがGoogleサービスへログインしたり、自動的にChatGPTコネクタの認証を引き継いだりすることはない。**本番の連携や定期巡回を新たに有効化したものではない**。

2026-11-08、ChatGPTからは**井上・ワコーフーズ・ヨシダ・イトウの実原本A1:O40をFORMULA形式で限定読取**してセルの型・見出し・数式の存在を個別確認。とくにワコーフーズは**G列「卸値」・I列「卸値（税込）」**の両方が価格候補で、共通パーサーが勝手に単価列を決めない必要がある。**この実資料確認はChatGPTコネクタ上の限定検査であり、新しいPython接続関数を実原本のGoogle API資格情報で実行したものではない**。コードの接続部分については[Google Sheets v4模擬サービスのテスト](../tests/test_supplier_sheets_multi_bridge.py)13件を追加した。

## 4社実資料のJAN/ASINを限定横断比較（ChatGPT接続・2026-11-08）

実Google Sheetsの4タブ（井上、ワコーフーズ、ヨシダ、イトウ）をそれぞれ`A1:O40`・`FORMULA`で読み、**ChatGPTのコネクタを使った一時的な比較処理**でJAN・ASINの重複候補を確認した。各資料の商品名/JAN非空の候補は38/6/39/6行、数値型JANは9/6/39/6行、形式上のASINがあるのは0/3/35/6行だった。

**この限定4タブ・計89候補行において、異なる取引先間の共通JAN/ASIN候補は0件。** 調べた4タブ以外・40行を超える範囲・メーカー別タブを検索していないので、全社の商品重複がないと解釈しない。数値型JANには先頭0消失の恐れがあり、チェックデジット形式だけでSKU確定としない。

これは**新Python`sheets_multi_bridge.py`に実データを通した結果ではない**。そのコードは架空データのテスト済みで、実認証クライアントによるPython E2Eは引き続き未実施。実値をGitHubに載せていない。匿名詳細：[Private共通知識の実資料比較記録](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/pilots/four-supplier-live-cross-lookup-2026-11-08.md)。

### 未解析タブで全件検索を止めない

`multi_source_readonly.normalize_selected_sources`は**あらかじめ指定された一部資料が空、または見出しを検出できなかった場合**でもほかの資料を処理し、`source_status_counts`（`parsed`、`empty`、`needs_review`）を匿名で返すよう改修した。検索時も`sources_with_parsed_headers`／`sources_not_searchable`を区別し、0件ヒットから「商品なし」と判断しない。予期しないパーサーエラーは隠さず停止する。架空の失敗・正常を混ぜた**4件のテストを追加**。

## Excel .xlsx / .xlsmの共通解析用ローカル接続（2026-11-08追加）

新しい[`local_excel_bridge.py`](local_excel_bridge.py)は、**利用者が権限を確認してプライベートなローカルフォルダへ置いたExcel**に限定し、Sheetsと同じ`normalize_selected_sources`および`search_selected_sources`へ渡す。ネットワーク・Google Drive・GitHubの認証を要求しない。勝手なフォルダ全走査、元ファイルの更新、マクロ/数式の実行、利益計算や自動発注はしない。

```python
from supplier_docs.local_excel_bridge import (
    SCHEMA_VERSION, MODE, inspect_selected_local_excel,
)

# 架空のローカルフォルダとファイル名。実ファイルの内容は公開しない。
approved = {
    'schema_version': SCHEMA_VERSION,
    'mode': MODE,
    'targets': [
        {'relative_path': 'vendor_a.xlsx', 'sheet_name': '見積もり',
         'document_type': 'quote_response'},
        {'relative_path': 'vendor_b.xlsm', 'sheet_name': '最終候補',
         'document_type': 'quote_response'},
    ],
}
# private_result = inspect_selected_local_excel(
#     root_dir='/private/authorized-supplier-files', manifest=approved,
#     search={'field': 'model', 'query': 'MODEL-001'},
# )
# print(private_result['public_summary'])  # 件数だけ
# 商品の値・ファイルパス・検索ヒットは PRIVATE なので共有ログに出さない。
```

**入力制限と安全確認**：対象を明示した1～5タブのみ、1シートA1:O40（600セル）、計最大3000セル。1ファイル20MB・指定ファイル合計50MBまで。対象ファイルは指定したルート内の相対パスに限定し、`..`、絶対パス、シンボリックリンク、未知拡張子、隠しタブ、存在しないシートを拒否する。各シートの存在・可視性を検証してからセルを読む。

`openpyxl.load_workbook(read_only=True, data_only=False, keep_links=False)`を使用。**.xlsmを読み取ってもVBAマクロを実行しない**。数式は評価済みの値でなく式文字列のまま読み、既存パーサーが仕入価格として推定計算しない。商品の**数値型JANも勝手に先頭0を復元しない**。

ログに出せる`public_summary`は読んだ資料数・抽出件数・見出し曖昧性・数式数のみ。**PRIVATE**の`private_normalized_docs`・`private_origin_manifest`・`private_hits`は原本ファイル名・商品名・JAN・ASIN等を含み得るので、GitHub・公開CI・一般ログへ出さない。

[4卸問屋の構造を模した架空Excel4ファイルによる14件の回帰テスト](../tests/test_supplier_local_excel_bridge.py)を用意（1ファイルはマクロ有効形式の拡張子`.xlsm`）。ファイル実データや契約秘密をCIに持ち込まず、**実取引先のExcelについてはファイル形式／シート構造の確認まで**である。新ブリッジによる実原本行の正規化結果はまだ未検証。[実フォルダ・形式の匿名確認記録](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/pilots/four-supplier-excel-bridge-2026-11-08.md)。

## CIと実運用の線引き

2026-11-08に調べた4社の**列見出し構造を模した架空の商品データ**を[15件のテスト](../tests/test_supplier_multi_source_readonly.py)で正規化・照会する。実JAN/価格・取引先の個別商品をCIへ渡さない。結果は正規化できる形のソフトウェア上の実証であり、**実際の4社の全商品行をプログラムに投入する一連の実運用試験ではない**。

次の工程で、権限のある私的実行環境から**1～5社の少量の実原本行をこの処理へ渡す**接続を安全に設計する。照合件数と問題点だけを公開安全な進捗へ記録し、秘匿原価や本番認証は扱わない。

方針：[Private共通知識の複数卸優先ルール](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/cross-supplier-development-priority.md)。Draft PR #1の範囲内・未マージ、本番WIF/Keepa/SP-APIへの変更なし。
