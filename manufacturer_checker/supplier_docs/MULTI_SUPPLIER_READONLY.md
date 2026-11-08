# 卸問屋横断の共通正規化・照会MVP（2026-11-08／開発用）

## 行内のPOS/ITFラベルをJANとは独立して検索する

[新しい行ラベル確認と使い方](ROW_LABELED_IDENTIFIER_REVIEW.md)：見出しが多段のままでも、商品行に`POSコード`・`ITFコード`という**独立のラベル**と隣接値があれば、明示した列番号から候補値のみ取得。文字列型・GS1チェックデジットを確認し、`pos_candidate`／`itf_candidate`の専用検索（`field='pos'`/`field='itf'`）を行う。**既存のJAN検索に自動混入させない**。`labeled_review`は検索候補だけの状態で、商品名、現行SKU、入数、仕入単価、利益は未確定。Excel/Sheets共通入口で同じ事前検証を使う。

実Excel2タブの限定構造検査は行ったが、**この新関数の実商品データでのE2Eは未実施**。架空データの20テスト成功、機密データはCIに送らない。

## 最新の共通機能：多段見出しを明示的に限定マッピング

[複数行見出しの明示マッピング手順](TIERED_HEADER_MANUAL.md)を追加。Excel/Google Sheets双方で`tiered_mapping`マニフェストを**読取前に検証**し、2～4行の見出し座標から**独立ラベルと一致する商品識別子だけ**を`mapped_review`として抽出できる。従来の`needs_review`・`parsed`とは区別する。`cost_amount`／ケース入数／税区分は不可、価格が原本にあっても`cost_present=false`・利益計算禁止。**実LeadOffの混合POS/ITF見出しはまだ安全上保留**。テストは架空データ17件、実原本の新たな人手マッピングE2Eは未実施。

## 最新検証：開発用Excelブリッジの実原本E2Eに成功

2026-11-08、**4卸問屋・指定5シート（各A1:O40）**を`local_excel_bridge.inspect_selected_local_excel`本体で読んで`multi_source_readonly.normalize_selected_sources`へ渡す**私的な実原本試験を完了**。3シート解析・2シート多段見出し`needs_review`。ブラックス`.xlsx`のケースでは52商品候補・数式45件、`.xlsm`のケースでは60候補・数式117件。**値を載せず件数だけ報告**し、JANとASINの限定完全一致検索を各1件試験。**原本ハッシュは全件一致**。異なる卸同士の同一商品確定や全行の読み込みではない。詳しい匿名証跡：[Private Repoの実E2E記録](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/pilots/four-supplier-real-excel-e2e-2026-11-08.md)。

同じ検証を複数社に繰り返す場合、**私的なJSONマニフェストのみを用いる匿名結果CLI**を使う。

```sh
# private authorized root and private JSON files are local to your environment.
python -m supplier_docs.local_excel_probe \
  --root /private/supplier-inputs \
  --manifest /private/selected-sheets.json \
  --search-manifest /private/private-lookup.json
```

標準出力は**件数・状態・警告のJSONだけ**。商品名・JAN/ASIN・価格・原本ファイルパス・検索語は出さない。入力不正の場合は**例外詳細やファイル名を標準エラーへ流さず拒否**する。CLI自体は架空Excelで[6件の回帰テスト](../tests/test_supplier_local_excel_probe.py)を実施した。**本番のDrive認証・自動ダウンロード・定期実行は持たない**。

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

## 実Excelで発見した複数行の見出しと共通ガード（2026-11-08）

Driveから読取許可された**4取引先・4つのExcelファイル・合計7シート**を一時的な私的処理環境で調査した。検証は**実ファイルの列構造**であり、新Python`local_excel_bridge`に個別仕入価格等を投入した本番実行ではない。

- **イトウ**：見積回答Excelの3行目に「商品名／JAN／ASIN／JAN／ケース入数／単価」。**JAN見出しが重複**。依頼側JANと回答側JANの来歴を別資料で確認済みだが、商品同一性は確定しない。
- **リードオフジャパン**：2シートとも**12～15行目に階層見出し**。商品コード、商品名・POS/ITFコード、入数、価格等が**複数行に分かれる**。**単一行として価格・入数・JANを誤結合しない**。
- **井上**：対象Excel内の2シートで見出しが1行目。1シートには品番／JAN／商品名／発注単位／下代（税抜）などがある。
- **ブラックス**：一次選別シートは**16行目**、別シートは**1行目**に商品列の見出し。卸値税抜／卸値税込など価格候補が併存し、**概算利益や定価を仕入原価として採用しない**。

[`header_layout_guard.py`](header_layout_guard.py)を追加し、最大40行×15列の**既に取得した行配列**から、
`single_row`／`multi_row_needs_review`／`no_reliable_header`／`empty` を判定する。
`single_row`は見出しの物理行番号を返す。
`multi_row_needs_review`は**複数行の見出しを勝手に1行へ統合せず**、共通解析で`needs_review`に分離する。他の資料の検索は続ける。
JANの重複・価格らしい見出しの複数存在を匿名件数として記録するが、価格の正本選択・出品SKU確定・利益計算はしない。

`multi_source_readonly.normalize_selected_sources`にこの事前判定を追加したので、**Sheets用／Excel用のどちらの入口でも同じ判定ルール**を使う。
`public_summary`は`header_layout_counts`、`sources_with_duplicate_jan_headers`、`sources_with_multiple_price_hints`の**匿名集計のみ**を返す。
実JAN・ASIN・卸原価・商品名は公開しない。

[4社に由来する見出し形式のみを架空行列にしたテスト](../tests/test_supplier_header_layout_guard.py)を追加。ソース内容の実際の全商品行をGitHubへ送っていない。[機密を除いた4社の原本確認記録](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/pilots/four-supplier-real-excel-header-geometry-2026-11-08.md)。

### 実Excel上で判定ロジックを限定実行した結果

上記4社の**実Excel4ファイル・7シート**の`A1:O40`に対し、私的な一時実行環境で同じヘッダー判定ロジックを直接適用した結果、**1行ヘッダー5シート／複数行ヘッダー要確認2シート**、**同名JAN見出し重複1シート／複数の価格関連見出し3シート**を検出した。**これはコードの見出し部分の実ファイル試験**であって、`local_excel_bridge.py`と全`parse_rows`を実原本で通した完全E2Eではない。ファイルの生値・原価はログやGitHubへ残していない。

## CIと実運用の線引き

2026-11-08に調べた4社の**列見出し構造を模した架空の商品データ**を[15件のテスト](../tests/test_supplier_multi_source_readonly.py)で正規化・照会する。実JAN/価格・取引先の個別商品をCIへ渡さない。結果は正規化できる形のソフトウェア上の実証であり、**実際の4社の全商品行をプログラムに投入する一連の実運用試験ではない**。

次の工程で、権限のある私的実行環境から**1～5社の少量の実原本行をこの処理へ渡す**接続を安全に設計する。照合件数と問題点だけを公開安全な進捗へ記録し、秘匿原価や本番認証は扱わない。

方針：[Private共通知識の複数卸優先ルール](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/cross-supplier-development-priority.md)。Draft PR #1の範囲内・未マージ、本番WIF/Keepa/SP-APIへの変更なし。
