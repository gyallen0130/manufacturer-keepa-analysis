# GitHubの非公開リポジトリに更新履歴を暗号化保存（設計・未運用）

## 現在の状態

**追加課金・実サービス作成なし。** `supplier_docs.private_github_state` は、既存GitHubの非公開リポジトリを使って、取引先資料の**更新版・ファイルIDの一覧だけ**をFernet暗号化して保存するための試験用アダプタです。アプリケーションは自分ではGitHubへログインせず、明示的に与えたHTTPセッションを使います。現在はモック通信でテストしており、実GitHubの非公開リポジトリのデータを書き換えていません。

## 追加費用を抑える想定構成

- 既存または承認済みの**専用非公開GitHubリポジトリ**でワークフローを実行する。コード開発用の公開 `manufacturer-keepa-analysis` は本番状態の保存先に**絶対使用しない**。
- Private Repo内の `supplier-monitor-state` **専用ブランチ**と、固定された `private-state/supplier-docs-inventory.enc` だけを更新候補にする。初期ブランチを自動作成しない。アダプタは `GET /repos/OWNER/REPO` でPrivate・未アーカイブを、 `GET /branches/supplier-monitor-state` で保存用ブランチの存在を実行時に確認する。
- 初回は明示的な基準点承認が必要。2回目以降は前回のGit blob SHAを `PUT /contents` の `sha` パラメータへ渡し、**現在の内容と違う場合は上書きを拒否**。競合・失敗時の自動再試行はせず、読直し・承認履歴の照合が必要。
- 変更分の更新には、**更新対象すべてのEd25519レビュー署名**と担当者の信頼済み公開鍵が必要。照合が失敗したら保存をしない。Workerは承認秘密鍵を持たない。
- 更新版の暗号化キーは**GitHubリポジトリのSecrets等、コードや履歴と分離した非公開の管理先**で扱う。環境変数をログに出さず、シークレットを公開Repoやpull requestで渡さない。保存するのは**暗号文**のみで、ファイル内容・商品名・見積金額はGitHubへ保存しない。
- GitHub Actionsの `GITHUB_TOKEN` には専用ジョブで `contents:write` が必要になる場合があるが、**トークンはファイルパス単位で権限を限定できず、対象リポジトリ全体に及ぶ**。コードが置かれるブランチと保存先ブランチの保護・無関係なPRで実行不可・workflow_dispatch限定・受入れ済みコードのみ・権限設定レビューが必須。このコードだけで必要なGitHub権限管理が完成したわけではない。
- GitHub ActionsのArtifact／Cacheを唯一の永続保存先にしない。Artifact・ログには保持期限があり、Cacheは削除され得る。Gitの暗号文履歴を利用する案は保存期限を制御しにくい反面、従来の状態を復元できる可能性がある。

## 保存するデータ・保存しないデータ

- 保存する：承認フォルダ内に限定されたスプレッドシートのファイルID、MIME、更新版・更新日時、およびスナップショット形式のバージョン。**暗号化した状態のみ**。
- 保存しない：仕入価格、取引条件、商品一覧のセルデータ、Amazon/Keepa認証情報、サービスアカウントの鍵、レビュー秘密鍵、レビュー画面・本人認証情報。
- `read(key=...)` はPrivateを確認した上で暗号文の整合性とスナップショットの構造を検証。キーが違う、破損、対象ブランチがない、予期しないレスポンスは停止する。
- `initialize(..., approve_initial_baseline=True)` は1回限り。初回に存在する資料を**過去分として解析しない基準点**に設定するので、所有者の明示確認が必須。
- `advance_after_review(..., expected_sha=..., receipts=..., trusted_public_keys=...)` は既存のSHAが一致し、すべてのEd25519レビュー署名が正しい場合のみ暗号文を書き込む。差分がなければ書き込まない。**原資料の更新版を保存直前に再確認するロジックは呼び出し側の未実装課題**。

## Gitの性質から残るリスク

- **暗号文の過去版はGit履歴に残る**。非公開でも権限を持つ人がクローンでき、後に暗号鍵が漏れれば過去分も復号される可能性がある。キーの保護とアクセス権・バックアップ・ローテーションが重要。暗号文だけでもGitに置くことを許容できないなら、この案は採用しない。
- `GITHUB_TOKEN` は同一リポジトリ内で使う想定で、**別のリポジトリへの保存には通常そのまま利用できない**。別の専用保存リポジトリを採用するなら、GitHub App／細分化した権限の専用認証を検討するが、費用や管理負担も再評価する。
- **レビュー署名の永続監査記録はまだ連結して保存していない**。安全な自動確定には本人認証、監査記録の永続保存、ソース更新版の再照合、実行排他と障害時の復元試験が必要。
- 実運用前にGitHubのprivateリポジトリ残りActions無料枠・保存容量・請求設定と利用プランを確認する。**無料で運用できると保証するものではない**。ユーザーによる追加サービス承認なしに課金可能な設定を変更しない。

## 開発テスト

```bash
cd manufacturer_checker
python -m unittest discover -s tests -p test_supplier_private_github_state.py -v
```

**テストは全件架空のID、仮想のGitHub APIレスポンス、使い捨ての暗号鍵・署名鍵だけ**で実行します。Public RepoのPR CIでは書き込み権限を付けず、実HTTP通信は行いません。

公式仕様：
- https://docs.github.com/en/rest/repos/contents
- https://docs.github.com/en/actions/concepts/security/github_token
- https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository
- https://docs.github.com/en/organizations/managing-organization-settings/configuring-the-retention-period-for-github-actions-artifacts-and-logs-in-your-organization
- https://github.com/pricing
