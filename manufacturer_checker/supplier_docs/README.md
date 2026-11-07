# 取引先資料の共通解析（試験版）

Google Driveのメーカー／卸問屋別フォルダにある見積書・商品リストの**表部分**を、出典・リスク付きの共通JSONに変換する試験版です。従来のKeepa分析・Colab実行・GitHub Actionsとは接続していません。

**対象**：.xlsx / .xlsm / .csv / .tsv と、Google Sheets v4の values.get が返す2次元配列。PDF解析、Driveの全フォルダ巡回、定期同期、Keepa照合、利益再計算、発注は未実装です。

## 使い方

既存コードと独立したモジュールです。APIキー不要のローカルファイル解析：

    cd manufacturer_checker
    pip install -r requirements.txt
    python -m supplier_docs.cli --input /path/to/quote.xlsx --sheet-name 見積もり --document-type quote_response

Google Sheetsを読み取る場合、**専用のサービスアカウントを鍵なしで代理認証**します。ログイン元のGoogleアカウント（ColabやCloud ShellのADC）は、専用アカウントへ一時的に代理認証できる必要があります。PythonコードからSheets APIへ渡すのは **`spreadsheets.readonly` だけの15分間の代理認証トークン**です。

### 最初に必要なGoogle Cloud設定（ユーザーによる操作）

1. 取引先資料用に、新規の専用サービスアカウント（例：`supplier-docs-reader@YOUR_PROJECT_ID.iam.gserviceaccount.com`）を作成する。**既存のSP-API用サービスアカウントや秘密鍵を流用しない**。
2. 同じCloudプロジェクトで **Google Sheets API** と **IAM Service Account Credentials API** を有効にする。
3. Colabでログインする本人のGoogleアカウントに、**この新規サービスアカウント単体だけ**の `roles/iam.serviceAccountTokenCreator` を付与する。プロジェクト全体には付与しない。
4. テストしたいGoogle Sheetsファイル**1件だけ**を、そのサービスアカウントのメールへ **閲覧者（Viewer）** で共有する。初回から取引先資料フォルダ全体は共有しない。
5. サービスアカウント鍵（JSON/PEM）は**作成しない**。認証の準備やユーザー承認ができるまでは接続試験を実行しない。

設定後、[Colabで安全な集計試験を開く](https://colab.research.google.com/github/gyallen0130/manufacturer-keepa-analysis/blob/feature/supplier-docs-normalizer-v1/notebooks/supplier_docs_readonly_smoke.ipynb) から手順に沿って実行できます。NotebookはPythonコードを検証済みコミットに固定して取得し、IDは非表示入力、結果は集計のみ表示します。ChatGPTのGoogle Driveプラグインから認証情報を取得することはできません。

同様に、Colabではなく**ユーザー自身の認証済みローカル環境**でCLIを実行する場合：

    python -m supplier_docs.cli --sheets-id YOUR_SHEET_ID --sheet-range "'見積もり'!A1:L40" --document-type quote_request --impersonate-service-account supplier-docs-reader@YOUR_PROJECT_ID.iam.gserviceaccount.com --summary-only

`--sheets-id` では専用アカウントの指定と `--summary-only` が**必須**です。ユーザーADCを暗黙に直接利用したり、取引先名や卸値などの生データをコンソール出力したりするモードは拒否します。

Google Workspaceでは、サービスアカウントのアドレスを対象シートの**共有先**としてViewerに指定できます。権限と共有設定の詳細は [Googleの公式説明](https://developers.google.com/workspace/guides/create-credentials)、鍵なし代理認証は [google-authの公式説明](https://googleapis.dev/python/google-auth/latest/reference/google.auth.impersonated_credentials.html) を参照してください。

document-type は manufacturer_list / quote_request / quote_response / catalog / price_revision から**原本の性質を確認して**選択してください。見積依頼を回答済み見積として扱わないため、自動推定しません。見出し行は先頭20行から推定し、必要なら --header-row 2 を指定します。対象の表範囲は原本に合わせて狭く指定してください。

## 安全なAPI接続の試運転

上の鍵なし代理認証手順に従い、まず1シートの40行以内だけを `--summary-only` で試験してください。サービスアカウントはViewer権限のみ、トークンは15分の `spreadsheets.readonly` スコープです。

- `--sheet-range` は有限のA1範囲（最大50,000セル）しか受け付けません。
- `--summary-only` の表示はレコード数と警告・リスクコードの件数のみです。ファイルID・商品名・JAN・ASIN・卸値・取引条件の原文を表示しません。
- ソースコードにはSecret、実Google Sheets ID、取引価格・顧客情報を保存しません。
- 実認証・権限付与は各Googleアカウント側の所有者操作が必要です。このPRのCIは合成データのテストのみです。
- Google Sheets APIの読み取りだけを許可していますが、Colabなどでログインする**元のアカウントの権限自体を縮小するものではありません**。APIへ渡す専用アカウントを最小化する設計です。

## 出力と保護

既定の標準出力は**原価と備考を伏せた**JSONです。元ファイルへの更新はしません。

卸値などの詳細が必要な場合のみ、アクセス制限されたローカル保存先を指定します。

    python -m supplier_docs.cli --input /path/to/quote.xlsx --document-type quote_response --include-sensitive --output /private/path/result.json

保存先は新規ファイルのみ（既存ファイルは上書きしない）、Unix系では所有者のみのアクセス許可を指定します。OSの設定や保存先共有権限も別途確認してください。**実見積、原価、取引先の個人情報、出力したJSONをGitHubへコミットしないでください**。ファイルのパスや原本のURLにも取引情報が含まれる場合があります。

出力には source_file_id / source_sheet / source_row、JAN（文字列）、ASIN候補（照合未確定）、発注単位、税区分、既存利益判定の状態、リスクコードを含みます。すべての行の decision は needs_confirmation で、仕入れの自動承認はしません。

## 注意点

- JANがExcel側で数値として保存されていた場合、失われた先頭ゼロは復元できません。警告します。
- ASINが無題列にある場合は、B0で始まる10桁だけを**候補**として扱い、確認を要求します。
- 見積依頼・見積回答シートでは、見出しが空欄のASIN列や利益判定列を**5行以上の高一致率かつ80%以上の行網羅率**で推定できます。推定した列は `inferred_columns` と `summary.inferred_fields` に明示し、各行へ `ASIN_UNLABELED_COLUMN_INFERRED` / `PROFIT_UNLABELED_COLUMN_INFERRED` の警告を残します。候補列が複数ある場合や根拠が不足する場合は推定しません。原本の確定的な見出しとしては扱いません。利益ラベルはあくまで**原本の既存判定**であり、利益再計算や仕入承認ではありません。
- **複数ASIN**が1セルにある場合、`asin_candidates`に全候補を残し、`asin_candidate`（単一候補欄）は空にします。単品／セットを選びません。
- **卸側の商品名が空欄でAmazon名／ASINのみ**の行も失わず記録し、`SUPPLIER_PRODUCT_UNKNOWN`を付けます。
- **メーカー別シート**は`source_group`にシート名を保持しますが、シート名を契約先・製造元の確定情報に読み替えません。
- **取引条件がグループ先頭行にしかない**場合、明確な連続行の範囲で注意情報を継承し、メーカー切替や空行でリセットします。金額・原文は既定の出力へ含めません。
- 先頭ゼロの前に不可視文字が付いたJANは、除去したうえで警告します。元のコードが正しい保証はありません。
- 見出しの同義列が重複した場合は片方を推測で選ばず、その項目の抽出を保留します。
- 黒字（競合によっては赤字）等は条件付きと判断し、単純に黒字として採用しません。
- EC不可・取り扱い不可・直送限定・定価販売等はリスクコードとして記録します。規制や契約上の実効性を判断する機能ではありません。
- Google Sheetsの表示形式で失われたJANの0や数式の計算結果の検証は保証しません。
- PDF、結合セルの特殊な配置、複数の独立した表を持つシート、Excelの外部リンク等は未対応です。原本を読んで手動確認してください。

## テスト

    cd manufacturer_checker
    python -m unittest discover -s tests -p 'test_supplier_docs.py' -v

異なる列順・複数ASIN・ケース条件を架空データで検証しています。テストはすべて架空データです。実際の取引先・仕入価格・Drive IDはコードに含めません。

業務上の項目定義は非公開の amazon-business-knowledge/suppliers/field-schema.md を参照してください。公開リポジトリから直接参照・取得できるとは限りません。

**実Google Sheetsとの照合（2026-11-08）**：`FORMATTED_VALUE` の返却値は数値JANも文字列として返すため、数値セルから先頭0が失われているか判定できません。`FORMULA` に変更して生の数値型を保持し、式は文字列として処理・不採用とします。実資料の金額・原文をGitHubに保存しないでください。その後、専用サービスアカウントによるGoogle Colabからの実接続と先頭40行の読み取り・集計（39件）は成功しました。ただし、列推定機能を含む更新後の実データ再検証は未実施です。
