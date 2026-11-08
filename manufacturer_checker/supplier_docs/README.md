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

## 複数シートの安全な取得（開発用アダプタ）

`supplier_docs.readers.sheets_visible_tabs` は、指定されたSpreadsheetの**表示中の通常シート**の名前だけをSheets APIのメタデータで取得します。非表示・オブジェクトシートは対象外です。

`supplier_docs.readers.sheets_selected_tabs_summary` は、呼び出し元が**タブ名と文書種別を明示したシートだけ**を指定行数・指定列まで読み込み、匿名の件数・注意コードを集計します。

- 文書種別はタブごとに指定が必要で、`manufacturer_list` / `quote_request` などの自動推測はしません。
- 既定は最大10タブ、タブあたり先頭40行・A:L列。合計50,000セルを超える指定を読み取り前に拒否します。
- 非表示・未指定・存在しないタブを勝手に読み込みません。見出しが判定できない場合は `needs_review` として扱います。
- 返すのはタブ順の番号・件数・リスクコード等だけです。タブ名、原価、JAN、ASIN、商品名、原本IDは集計結果に含めません。
- 現時点では**Pythonライブラリの開発用機能**です。既存のColab試運転やGitHub Actions本番ワークフローから自動実行するようには変更していません。実データでの複数シート一括実行は未検証です。

## Google Driveの更新差分検出（開発用、未接続）

`supplier_docs.drive_delta` に**メタデータだけ**を使った読み取り専用の差分検出部品を追加しました。Drive v3 の `files.list` で、利用者が明示的に許可したフォルダの**直下**だけを、ページ数・件数の上限付きで確認します。`name`（ファイル名）や原本の本文、共有権限は取得対象に含めません。

- `scan_approved_folder(service, folder_id=...)`: 1フォルダの完全なメタデータ一覧（ファイルID、MIMEタイプ、更新版番号／更新時刻）を、上限10ページ・500件で取得。**子フォルダは開かず**件数だけを集計。
- `scan_explicit_folder_set(service, folder_ids=[...])`: **承認済みIDを明示列挙**した複数フォルダを対象にする。既定上限は160フォルダ・240ページ・10,000項目。指定外のフォルダを探索したり、My Drive全体を検索したりしません。途中の失敗・取得漏れがあれば全体を不採用。
- `plan_changed_files(previous, current)` / `plan_explicit_folder_set(previous, current)`: 完全な2回分の一覧を比較し、初回は**基準点のみ**作成。2回目以降、新規・更新・不変・見えなくなったファイルを区別。アクセスが消えた／移動した可能性があるファイルは**削除せず要確認**とします。
- IDを含む一覧と作業候補は**機密情報**です。戻り値の `summary` だけを集計共有し、ID・フォルダ名・生のメタデータをGitHubや公開ログへ保存しないでください。
- まだスケジューラ、認証、永久保存、資料の実ダウンロードや自動解析とは**接続していません**。これらの関数は外部処理を自動起動しません。実資料への `files.list` 実行も未実施です。

**実運用前の追加条件**：現時点の専用サービスアカウントには *Google Sheets 2ファイルへのViewer共有* しかありません。Driveフォルダの巡回には所有者の明示的な許可が必要で、Drive APIの有効化、鍵なしの **Drive metadata readonly** スコープ（`https://www.googleapis.com/auth/drive.metadata.readonly`）と、**許可した対象フォルダの閲覧権限**を別途準備する必要があります。既存の `spreadsheets.readonly` だけではDriveのフォルダ一覧取得はできません。フォルダ全体を安易に共有せず、承認済みの対象範囲を明文化してから実装します。

## 差分スナップショットの暗号化保存と解析候補キュー（開発用）

`supplier_docs.snapshot_store` に、Drive一覧の**ファイルID・更新版番号をローカル暗号化して保存**する試験用モジュールを追加しました。用途はLinux/POSIX環境に限定しています。原本のコピーや仕入原価そのものは保存対象に含みません。

- `write_encrypted_inventory(path, key=..., snapshots=..., expected_revision=...)`: 呼び出し元が明示的に承認した一覧だけをFernetで暗号化し、所有者だけがアクセスできる0700ディレクトリに0600ファイルとして原子的に保存。新規保存は上書き禁止、更新には直前に取得した暗号文リビジョンが必要です。
- `read_encrypted_inventory(path, key=...)`: 暗号文の改ざん・復号失敗・危険な権限を拒否して、前回の一覧と照合用リビジョンを復元します。
- `review_queue(previous, current)`: 新規・更新ファイルだけを私的な確認キューへ振り分けます。Google Sheetsは閲覧専用解析の候補、Excel・CSV等のファイルは未実装の取得処理を要求する**手動確認候補**にします。ファイルID・フォルダIDはキュー内の機密情報であり、公開するのは集計欄のみです。
- `finalize_inventory(previous, current, completed_locations=..., reviewed_unavailable=...)`: 初回は `approve_initial_baseline=True` の明示的許可が必要です。2回目以降は**更新対象の全件処理と閲覧不可ファイルの確認が揃わない限り、基準点の更新を拒否**します。失敗時に古いスナップショットを保持して再試行できる設計です。

**運用上の重要事項**

- 暗号鍵は、別のアクセス管理されたSecret Managerなどで保持し、GitHubのコード・ノートブック・ログ・スナップショットと同じ保存場所には置かないでください。**鍵の発行・保管先・定期実行環境は未設定**であり、現時点では自動保存は稼働していません。
- 上記の関数は対象ファイルの自動ダウンロード・解析実行・仕入れ判断・発注を行いません。キューを実際のSheets API解析に接続する際は、対象ファイルとシートの許可リスト、文書種別、処理成功の記録を別途確認します。
- スナップショットには機密のファイルIDが含まれます。暗号文であっても、既定でGitHub・共有Drive・公開CIログへのアップロードは禁止します。
- 現状の保存APIは**単一の書込プロセスを想定**しており、複数プロセスの同時実行ロック・クラウド永続化・障害復旧は未実装です。これらが整うまでは本番の定期実行に使用しません。

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
    python -m unittest discover -s tests -p 'test_supplier_*.py' -v

異なる列順・複数ASIN・ケース条件を架空データで検証しています。テストはすべて架空データです。実際の取引先・仕入価格・Drive IDはコードに含めません。

業務上の項目定義は非公開の amazon-business-knowledge/suppliers/field-schema.md を参照してください。公開リポジトリから直接参照・取得できるとは限りません。

**実Google Sheetsとの照合（2026-11-08）**：`FORMATTED_VALUE` の返却値は数値JANも文字列として返すため、数値セルから先頭0が失われているか判定できません。`FORMULA` に変更して生の数値型を保持し、式は文字列として処理・不採用とします。実資料の金額・原文をGitHubに保存しないでください。その後、専用サービスアカウントによるGoogle Colabからの実接続と先頭40行の読み取り・集計（39件）は成功しました。その後、列推定機能の更新後も井上のColab再テスト成功、ワコーフーズについても専用SAで29件を解析し、重複する卸値列・複数ASIN候補を正しく保留しました。**手動の接続テストは2社分完了**しました。Driveのメタデータ差分検出は合成データのみで検証済みです。
