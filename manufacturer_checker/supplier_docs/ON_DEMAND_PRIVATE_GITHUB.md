# GitHub経由でメーカーGoogle Sheetsを必要時に参照する機能（開発用・未有効化）

## この段階でできること

- `on_demand_reader.py` は事前承認されたGoogle Sheets（最大3件・各最大4タブ・合計7,200セル、各タブA1:L100固定）を**Google Sheets v4読み取り専用**で取得し、既存のメーカー資料パーサーでJAN・ASIN・商品名・価格・注意事項などを構造化してメモリに返す。
- `manual_sheet_probe.py` は、GitHub Actionsの**非公開リポジトリ・mainブランチ・特定workflow・手動起動**の確認後に、専用Readerサービスアカウントで取得を試みるための入口。出力は**件数などの匿名集計だけ**。詳細な価格・取引条件・メーカー名・ファイルIDはGitHub Actionsログに載せず、終了時にメモリから破棄する。
- `auth.build_readonly_sheets_service_from_wif_adc()` は、既存のGitHub WIF認証による**Reader SAの短期認証情報**を使い、`spreadsheets.readonly` を要求する。長期サービスアカウント鍵JSONの作成・登録を前提にしない。
- `templates/supplier-readonly.yml` は**公開開発リポジトリ内のテンプレート**であり、`.github/workflows` に配置していないため、ここから実際のGoogle認証は起きない。対象Private Repoの承認とGoogle側WIF/IAMの確認が終わるまで使わない。

## まだ実現していない部分

**今回のコードだけでは、GitHubからいつでも実際の価格一覧を閲覧できる状態にはならない。** 原本の詳しい解析結果は、意図的にGitHubのログや公開Artifactに出さない。利用者／ChatGPTに機密データを安全に渡すためには、認証されたプライベートな配信・表示方法が別途必要。Private Repoにコピーしても、秘密のファイルIDを含む設定や価格のログを無制限に保存してよいわけではない。

Google Driveのフォルダ階層の一覧、Excel・CSVの実ダウンロードと解析、更新差分の自動保存、常時実行・予約発注も未接続。現時点の最小構成は**承認済みのGoogle Sheetsを手動で読取**するだけなので、広いDriveメタデータのOAuth権限は不要。

## Private GitHub Actionsの想定手順（未設置・未認証）

1. 実行主体となる**専用の非公開リポジトリ**と、保護できる実行コード・監査できる承認手順を決める。現在の `amazon-business-knowledge` の未保護mainを自動機密処理の既定保存先にしない。
2. レビュー済みの `manufacturer_checker/supplier_docs` コードと必要な依存コードをprivateリポジトリへ安全に配置する。公開開発中の未マージPRブランチを毎回追跡するのではなく、**レビュー済みの固定版**を使う。
3. `templates/supplier-readonly.yml` をPrivate Repoの `.github/workflows/supplier-readonly.yml` へ置く。ただし今は**まだ置かない**。動くコードの確認と、環境の料金・セキュリティ審査が先。
4. Google CloudのWIF providerとReader SA（既存SP-API用とは別）を確認。Google**側のprovider条件**には不変のGitHub `repository_owner_id`・`repository_id`、`refs/heads/main`、`workflow_dispatch`、実行workflowの完全な `workflow_ref` の一致を設定する。GitHub環境変数やworkflowの `if:` はこれを代替しない。Reader SAには**対象Google Sheetsだけ**をViewer共有する。既存の権限拡張はユーザー承認後にのみ。
5. Private RepoのVariablesに `SUPPLIER_WIF_PROVIDER` と `SUPPLIER_READER_SA`、Secretsに `SUPPLIER_READ_MANIFEST_JSON` を**本人の明示承認後**に設定する。Repo全体のSecretsへアクセスできるworkflowの管理・PRイベント等の権限を審査する。
6. 初回は**手動1回・指定1ファイル**で、GitHub Actionsが匿名集計だけを表示し、原本を編集していないことを確認する。テストに失敗した場合、秘密のAPI例外やファイルIDをログへ出さずに終了する。**この試験はまだ実施していない**。
7. GitHubの共有ドル建てコンピュートクレジットの当月使用額、課金を停止する予算設定、Google APIの現行割り当てを確認する。追加費用がかかる場合は勝手に利用開始せず、先にユーザーの明示承認を得る。

Private RepoのSecretとなるマニフェスト形式（以下は**架空データ**）：

```json
{
  "schema_version": "supplier-manual-sheets-read-v1",
  "mode": "manual_readonly",
  "targets": [
    {
      "spreadsheet_id": "fake_private_sheet_1234",
      "tabs": [
        {"title": "見積もり", "document_type": "quote_response"}
      ]
    }
  ]
}
```

対応文書種別は `manufacturer_list`、`quote_request`、`quote_response`、`catalog`、`price_revision`。指定外シートは閲覧せず、シートが非表示・不存在の場合はセル内容を1つも読まない。Formula文字列の評価、価格に基づく自動仕入れ判断も行わない。

## 安全上の重要な区別

- **公開PR内の単体テスト**は架空のGoogle APIレスポンスだけ。実ファイルID、実取引先資料、認証情報の送信はない。
- **Private GitHub WIF実行**は、利用者が権限のある対象ファイルにしかアクセスできないよう、Google側のサービスアカウントとproviderのIAMが正しく設定されて初めて安全に使える。プログラムの環境変数チェックは補助的。
- **実際のGoogle Driveフォルダをいつでも探せる仕組みではない**。今はシートIDの事前許可リストを使い、参照できる対象を明確にしている。
- **詳細データの安全な取得窓口は未完成**。今のGitHub Actionsログは匿名件数だけ。機密を必要とする回答や解析は、別途アクセス制御された実行／表示の導線を整備する必要がある。
- Google API、GitHub Actionsの認証と請求、専用サービスアカウントの共有設定、Private Repoの導入は**未実施・未変更**。既存のSP-API本番環境は不変。

## 参考

- [Google Sheets API - 指定範囲の値を読み取る](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/get)
- [GitHub WorkflowsのOIDC](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-google-cloud-platform)
- [Google Cloud - GitHub ActionsとWIF](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)
- [Google GitHub Actions auth (公式アクション)](https://github.com/google-github-actions/auth)

**このファイルは計画と開発用の手順です。導入の承認書や本番稼働の証明ではありません。**
