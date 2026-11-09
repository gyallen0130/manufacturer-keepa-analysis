# GitHub→Google Drive Reader WIF: 変更しない実設定の検査（未運用）

**段階：Private Repo／Google Cloudの実認証は未実施。GitHub側の読み取り専用メタデータと、既存Google Drive接続のファイル共有状況は別経路で確認できている。IAMやGitHub Secrets／Variablesに書込んでいない。**

## 実地で確認できた点（2026-11-08）

- Google Drive上の既存の**2件のGoogle Sheets**は、ChatGPTに連携されたDriveからメタデータを閲覧できる。指定Sheetのタブは表示可能。
- 2ファイルとも、Driveの共有権限に**既存の専用 `supplier-docs-reader@...` サービスアカウントの`reader`権限**を確認した。ここで実際のサービスアカウントの完全なメールアドレス／ファイルIDを公開リポジトリへ書かない。
- これは**ChatGPT側のGoogle Drive接続**による確認であり、**Private GitHub Actions→Google WIF→Reader SAでのアクセストークン取得を証明していない**。
- 既存Private Repoの`main`はGitHub Branch API上は`protected: false`。Freeでルールセット保護を使えないことを踏まえ、**Google認証元をより厳しく固定する案**を加えた。実GCP IAMとGitHub Actions課金残量は未取得。

## 新しいオフライン検査（`pinned_wif_audit.py`）

`review_observed_reader_wif` は、権限を持つ人が**別途読み取り専用で取得した**次の3種類の状態を、公開ログに具体的なIDや鍵を出さずに照合する。

1. GitHubリポジトリ：所有者とリポジトリの**変更されない数値ID**、private、default branch`main`、非アーカイブであること。
2. Google WIF provider：既存の**専用Provider**、GitHub公式OIDC issuer、`google.subject=assertion.sub`、カスタム属性マッピング、条件式が**レビュー済みの値と完全一致**すること。
3. Reader専用SAのIAM policy：`roles/iam.workloadIdentityUser` は、専用WIF pool内の該当**repository_idと完全一致するprincipalSet**だけに付与され、不要な外部principalSetが混在しないこと。

**重要な追加条件：** provider条件に、既存の`repository_owner_id`、`repository_id`、`refs/heads/main`、`workflow_dispatch`、`workflow_ref` に加えて、`repository_visibility=='private'`、`runner_environment=='github-hosted'`、**レビュー済みの`workflow_sha`と実行ソースの`sha`両方**を含める。

理由：`workflow_sha`（workflowファイルのコミット）だけでは、`checkout`された他の解析コードの同一性を保証できない。別途`sha`（実行するリポジトリのコミット）も照合する。**プログラムとWorkflowのどちらかの変更によりSHAが異なれば、Google側は認証を拒否する**ことを狙う。変更したい場合はその都度コードをレビューし、権限がある担当者がGCPの条件式を更新する必要がある。これは無料プランでの1つの回避策候補であり、手間がかかる。

ただし、**GitHubの第三者ActionとPython依存パッケージまで暗号学的に固定する仕組みではない**。公開版の`checkout@v4`、`setup-python@v5`、`auth@v3`、`upload-artifact@v4`および依存パッケージは、採用前にSHA／ハッシュ固定・コードの供給元をレビューする。Branch保護が未確認であれば実行権限やSecret変更権限のリスクも継続する。秘密の仕入価格がGitHub Runnerのメモリを通る以上、この制約は重要。

`expected_pinned_provider_condition(...)` が出すCEL条件式は**実GitHubのIDを含む機密設定値**なので、公開GitHub CI・チャット・ノートブック出力に貼り付けない。

## 今回の変更がまだ行っていないこと

- Google Cloud IAM/WIF providerの読み取りAPIに認証して**現在の実Provider設定を取得したわけではない**。利用可能な接続には、Google Cloud IAMの読み取り操作がないため。必要なら所有者がGCPコンソールで当該Providerの画面を確認するか、権限を付与された環境から安全にread-onlyスナップショットを取得して検査する。
- GitHubのSecrets・Variables・workflowの追加や実行、serviceAccountTokenCreatorやworkloadIdentityUserロールの付与は行っていない。
- 実際のGitHub OIDC tokenの発行やGoogle STS経由のアクセストークン交換は**未実施**。同じGitHub Repo/Branchの実Workflow SHAとソースコミットSHAがどの値になるかの検証も、本番実行前に必要。
- GitHubの**ドル建て共有コンピュートクレジット**の当月残額／課金停止設定とArtifactストレージ使用料は未確認。有料プランや新しい課金可能なGCPリソースは導入しない。
- メーカー資料の価格やJANは、公開GitHubに置いていない。実GitHub→Google Sheets→暗号化Artifact→本人Windows復号の一連のテストはまだ未完了。

## 初回接続を許可する前の判断

Google側Provider・Reader SA IAMの実読み取り、コードと依存の完全性、Private Repoの運用権限、本人のWindows暗号鍵保存・復号、GitHub Billingの確認が必要。今回の**開発用オフライン検査が成功しても本番への実行承認ではない**。

公式：
- https://docs.github.com/en/actions/reference/security/oidc
- https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines
- https://github.com/google-github-actions/auth
