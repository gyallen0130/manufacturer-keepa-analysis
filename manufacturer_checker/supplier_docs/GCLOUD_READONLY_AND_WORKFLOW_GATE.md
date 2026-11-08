# GitHub→Google Reader実接続前のread-only検査手順（まだ本番未接続）

## 実装したこと

`gcloud_wif_readback.py`は既存の専用ReaderサービスアカウントとWIFプロバイダーを、**本人が承認した場合だけ、読み取り専用で確認**する補助モジュールです。実環境への認証はまだ行っていません。

発行できる`gcloud`サブコマンドは次の2種類のみです。

- `gcloud iam workload-identity-pools providers describe ... --format=json`：指定されたGitHub用OIDCプロバイダーを読み取る
- `gcloud iam service-accounts get-iam-policy ... --format=json`：指定された専用ReaderサービスアカウントのIAMポリシーを読み取る

`create`、`update`、`set-iam-policy`、`add-iam-policy-binding`、`auth login`、`workflow_dispatch`は呼び出しません。実行中の生JSON・Googleのエラー・アカウントIDは通常ログに出さず、内部メモリで`pinned_wif_audit.py`へ渡します。Google Sheetsを読み取らず、販売条件も取得しません。

### 実行条件

コードは**明示的な所有者の`owner_approved_readonly=True`** がない限り実際の`gcloud`を呼びません。あらかじめ信頼できるローカルPCでGoogle Cloud CLIがインストール済みで、Google CloudのIAM／WIFを読み取れる権限があるユーザーがログイン済みである必要があります。**この開発でCLIをインストール、ログイン、APIを実行したわけではありません**。

設定には以下を**別の非公開ローカル領域**で準備する必要があります。GitHubの公開開発Repo、CIログ、チャット、Colabには実IDやポリシーを掲載しません。

- 既存の専用Reader SA名、専用WIF providerの完全リソース名
- 非公開GitHubリポジトリの独立に取得した所有者IDとリポジトリID
- セキュリティレビュー済みの`workflow_sha`と`sha`（両方40桁）
- GitHub公式APIから読み取った**同じprivateリポジトリ**の情報
- 読み取り専用CLIを実行するアカウントの権限確認と、支払い設定・Actions無料枠の確認

関数`inspect_readonly_cloud_wif`が、これらの入力とread-only取得済みのProvider・IAMを検査します。**現時点では操作用CLI/GUIを提供していない**ため、これは将来の信頼済み実行環境から呼ぶための開発部品です。

## GitHub Actionsのサプライチェーン検査

非公開実行環境用の**未設置テンプレート**`templates/supplier-readonly.yml`は、公式4 Actionsのコミットをタグではなく40桁SHAに固定しました。

| Action | 取得して固定したSHA（2026-11-08） |
|---|---|
| actions/checkout v4 | `11d5960a326750d5838078e36cf38b85af677262` |
| actions/setup-python v5 | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| google-github-actions/auth v3 | `7c6bc770dae815cd3e89ee6cdf493a5fab2cc093` |
| actions/upload-artifact v4 | `ea165f8d65b6e75b540449e92b4886f43607fa02` |

SHAの参照値はGitHubのタグから取得したものですが、**タグに指されているコードの完全な独立監査や第三者の安全性を保証するものではありません**。将来タグが更新されても実行コードが変わらない利点があります。

`private_workflow_integrity.py`は、テンプレートの4 Actionsのコミット固定、手動`workflow_dispatch`・private・main限定、最小限の`permissions`、X25519暗号化Artifactだけの1日保存を構造的に検査します。ただし**完全なYAMLパーサー／セキュリティスキャナではありません**。

**Pythonの依存ライブラリを22件のLinux/Python 3.11向けwheelで固定しました。** 2026-11-08の公開・架空データPR CIで公開PyPIのwheelをダウンロードしてSHA-256を計算し、`approved-requirements-hashed.txt`へ記録。テンプレートは`pip install --require-hashes --only-binary=:all:`でインストールし、別の仮想環境で**実際のSHA照合・pip check・重要モジュールのimportに成功**しています。`private_workflow_integrity.py`は実ロックを検査し、**次の人手レビューに進める**判定を返します。

ただし、**SHA一致はパッケージの無害性や出所を証明しません**。Private Repoのアクセス権、Google WIFの実設定、GitHub Actionsの課金とArtifact保存料、ユーザー鍵の安全な保管・実データの接続は未確認です。したがって本番は引き続き**No-Go**。詳細は[PRIVATE_HASHED_WHEEL_LOCK.md](PRIVATE_HASHED_WHEEL_LOCK.md)。

## 認証上の重要な注意

- GitHub OIDCの`workflow_sha`（ワークフローを含むGitコミット）と`sha`（実行ソースのコミット）の両方をGCP側で固定する条件を案として用意済みです。どちらかが変われば、利用前に改めてレビューする設計です。ただし**OIDCトークンの実発行・Google WIF交換は未実証**。
- WIFプロバイダーの属性マッピングは、`google.subject`・repo ID・workflow ref・SHAなどを対象とする。GitHubの環境変数だけで制限しても、Google側IAMの制約にはなりません。
- Google Drive接続で確認済みなのは**既存2ファイルに専用Reader SAのreader共有が付いていること**だけです。これはGitHub認証成功の証明ではありません。
- 既存Private Repoのmainが未保護なので、変更権限・Secret設定権限・第三者Actionsの固定が必要です。実Private Repoへのworkflow設置、Google Cloud IAM、Secretsや課金設定、SP-APIには変更を加えていません。

## 次の進め方

信頼済みのPrivate Repoの権限制限と固定済み依存wheelの安全性を独立に審査し、GitHub Billingの無料枠と支払停止条件が確認できた後、所有者の承認に基づき最小限のWIF条件を設定して、**既存の1 Google Sheet／1タブを手動1回**だけ読み取る実接続試験を行います。**現在は未実施**です。

参考（Google・GitHub公式）：
- https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines
- https://docs.github.com/en/actions/reference/security/oidc
- https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions
