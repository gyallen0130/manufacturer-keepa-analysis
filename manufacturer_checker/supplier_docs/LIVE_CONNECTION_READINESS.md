# 専用Google Drive Readerの実接続前チェック（READ ONLY）

更新：2026-11-09 JST。**開発Draft PR #1のみ／非公開Repoへのワークフロー設置・IAM変更・実認証は未実施**。

## 何を確認するためのモジュールか

`live_connection_readiness.py` は、以前から存在する`pinned_wif_audit.py`のWIF設定チェックと、**本人がすでに接続済みのGitHub・Google Driveから取得した現況**を、実商品や実ファイルIDを漏らさず統合する**純粋な判定コード**。それ自体はGoogleにログインせず、GitHub APIを呼ばず、ファイルも読まない。

入力は、信頼済みの呼出元がPrivateに取得した以下の5項目：
1. GitHub `get_repo` の実メタデータ：private／default branch main／archived false、変更不能なrepo ID・owner IDがあること。
2. GitHub `branches/main` の実結果：`protected`が真偽で明示されていること。
3. **明示的に選択した2 Google Sheets** の`get_file_metadata`：ネイティブSheets MIME、ファイルIDが異なり、双方に**同一の専用`supplier-docs-reader@`サービスアカウントがuser/reader共有されている**こと。ファイルメタデータの権限一覧が取得できない場合は確認できたと扱わない。
4. 既存`review_observed_reader_wif()`による**実Google CloudのWIF Provider／専用Reader IAMを独立に読んで検証したレポート**。repo ID、owner ID、workflow_ref、workflow_sha、実行commit sha、private、GitHub-hosted、manual dispatchの一致が必要。`True`だけを外部から申告することは証明ではない。
5. GitHub Billingで**無料枠・追加請求停止条件・Artifactストレージを別途独立に確認した事実**と、第三者Action・Python依存・コードSHAの独立審査完了。どちらも**Pythonが検証できるわけではない**。

## 分岐のルール

- どれか未確認・不一致なら`status='blocked_no_live_connection'`。未確認設定のままWIF/OIDCを起動しない。
- Privateリポジトリの`main`が未保護でも、Google側で**両SHAと専用repoを厳密に固定したWIF条件が実観測され、コード・依存審査を終えた場合に限り**、別途オーナーによる手動試験の検討対象にできる。これはbranch protectionの完全な代用ではない。
- すべての事前確認が揃っても`status='eligible_for_separate_owner_manual_test_review'`に過ぎず、**`manual_test_authorized=False`**。管理者の明示承認なしに自動実行・IAM変更・有料サービス作成・商品データ取得をしない。
- 返り値はすべて**匿名の状態名・真偽・不足チェック名**。GoogleファイルID、実取引先名、IAM principal、メール、version、原価・JANは返さない。
- 本モジュールは接続元・取得したJSONの本人認証、権限妥当性、出典署名までは実証しない。**信頼できる外部コネクタがPrivateの同一セッションで収集したものだけ**を渡す。公開APIにしない。

## 2026-11-09 実際の状態（識別子は非公開）

- 専用の共通知識GitHub Repoは**private、main、非アーカイブ**で管理者権限のある接続から読取可能。
- 実`branches/main`は`protected: false`。Private Repoのルールセットendpointは**有料プランへの変更が必要**との403。GitHub Freeのprivateレポジトリではrulesets/protected branchesが利用できないことは公式に記載。https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets
- 現リポジトリの`.github/workflows`フォルダ自体が**存在しない**。専用`supplier-readonly.yml`本番ジョブは未設置。
- 以前から選択・権限確認済みの**2件の実Google Sheets**では、どちらも同一の専用Readerの`user/reader`共有を再確認。ChatGPT接続のprojected metadataは現在もraw`files.version`を返さない。
- 実GCP WIF provider/IAMの独立取得・評価は**未実施**（この環境にIAM読み取り用接続がない）。GitHub Billingの残枠・支払停止条件は**未取得**。よって実接続は**NO-GO**。
- 現時点で`review_observed_reader_wif`を**実GoogleのProvider/IAM JSONを使って実行したとは主張しない**。本モジュールのCIテストは合成データのみで、本人確認やIAM審査を代替しない。

## 次の手順（実環境を書き換えない）

1. すでにある`manual_wif_preflight_cli` / `gcloud_wif_readback.py`の読取専用オーナー手順を、本人が承認した信頼済みCloud ShellまたはローカルGoogle Cloud CLIで実行する。IAMの生JSON、実メール、プロジェクト番号、repo IDは公開GitHub／チャットへ出さない。
2. GitHubの**Settings → Billing and licensing → Budgets and alerts**（画面表示は変わり得る）から、対象Private RepoでActionsとArtifactsの利用残額・停止設定を直接確認。設定・課金上限を変更するときは別途ユーザー承認を取る。公式：https://docs.github.com/en/billing/how-tos/set-up-budgets
3. 2つが完了しても、コード/Action SHA、依存wheel、権限境界、オーナー鍵保管をレビューした後、別途承認で**1ファイルのversionだけを読む手動Private試験**を実施。初回試験の前に一般公開Repoで試したり認証付きWorkflowを誤って有効にしない。
4. 版番号の実取得が成功した場合だけ、200行超の実メーカー資料の継続検索→112社索引との連携に進める。

費用を増やすことを前提にしない。Claudeは将来互換のみで現在は不要。

## 自動テスト

`test_supplier_live_connection_readiness.py`で、実状態相当のNO-GO、WIF未確認、branch保護なし、SHA固定/独立審査条件、ID重複/別Reader共有/公開Repo/欠落メタデータ、匿名結果の秘匿などの**13合成テスト**を実施。実Google/GitHub接続は含まない。
