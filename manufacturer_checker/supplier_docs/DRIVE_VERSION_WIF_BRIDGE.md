# 既存の専用ReaderからDrive v3 files.versionを取得する非公開接続

2026-11-09 / **開発Draft PR #1・main未マージ・実認証未実行**

## 今回実装したこと

以前から開発していた以下の部品を**再利用・接続**した。新しいGoogleアカウント、IAMロール、OAuth鍵、Secrets、課金サービスの作成は行っていない。

1. `auth.py` に `build_readonly_drive_metadata_service_from_wif_adc()` を追加：認証済み、専用Readerへ委任済みの**PRIVATE WIF ADC**から、`drive.metadata.readonly`というメタデータ専用スコープのGoogle Drive v3クライアントを構築する。Googleに直接ログインしたりIAMを変更したりしない。**ADCが本当に想定のReaderか、WIF条件が安全かは外部ホスト側で別途検証**が必要。
2. `supplier_drive_version.py` に `make_googleapiclient_drive_version_reader(drive_service)` を追加：既存クライアントの`files().get(fileId=..., fields='id,mimeType,version', supportsAllDrives=True).execute(num_retries=0)` を呼ぶ。返り値のファイルID、ネイティブSheets MIME、decimal int64の単調増加`version`を厳格に検査して、前回実装した継続スキャンの`get_source_revision`コールバックへ接続する。**元の商品セルや価格は読まない**。
3. `manual_drive_version_probe.py` に、明示した**1ファイルだけ**の`version`を確認し、**非機密の成功／停止フラグだけ**返す手動検査を追加。`--confirm-readonly`と、非公開環境変数`SUPPLIER_APPROVED_SHEET_ID`が揃わない場合、認証処理の前に停止する。

## 想定する手動・最小接続試験

**前提**：既存のPrivate GitHubリポジトリとGoogle WIFの**実Provider / Reader IAM条件**を独立にレビューし、Google Drive APIが利用可能か、当該Readerが**試験対象1資料にだけ閲覧権を持つ**こと、GitHub Actionsの料金・追加請求停止条件、使うコードと第三者ActionのSHAが固定されていることを確認する。

そのうえで、必要な認証済みPRIVATE WIF環境に限り、以下のように手動で実行する。**本テンプレートやコマンドは実GitHub workflowには配置していない。**

```bash
# PRIVATE実行環境でファイルIDを非表示入力・安全に設定する。
# GitHub公開Repo・公開ログ・チャットにはIDを貼らない。
# SUPPLIER_APPROVED_SHEET_ID はあらかじめ許可した1資料のみ。
# 同じPrivate環境で WIF ADC のサービスアカウントと対象共有を確認。
cd manufacturer_checker
python -m supplier_docs.manual_drive_version_probe --confirm-readonly
```

実行に必要な`SUPPLIER_APPROVED_SHEET_ID`は**Private環境変数**であらかじめ設定する。エラー時にログへ認証トークン、file ID、raw API JSONを出力しない。成功時も**版番号の値を印字しない**ので、外部メタデータの取得が可能になったことだけを判断する。

```python
from supplier_docs.auth import (
    build_readonly_drive_metadata_service_from_wif_adc,
)
from supplier_docs.supplier_drive_version import (
    make_googleapiclient_drive_version_reader,
)
from supplier_docs.supplier_scan_continuation import (
    scan_next_selected_supplier_sheet,
)

# WIF、IAM、本人認証、Google原本の共有を先に独立確認すること。
service = build_readonly_drive_metadata_service_from_wif_adc()
revision_reader = make_googleapiclient_drive_version_reader(service)
# scan_next_selected_supplier_sheet(...,
#      get_source_revision=revision_reader, ...)
```

このPython例は**アプリの認証を実装していない**。元の`fetch_formula_range`も、認証済みの別のGoogle Sheets読み取りアダプターが必要。`version`は現在のChatGPT Google Driveツールが返さないため、**このチャットでversionの実値取得が完了したわけではない**。

## リスクと制限

- `get_file_metadata(fields='...version...')` の現在のChatGPTコネクタは返り値を投影・整形するため、**versionが欠落**していた。Google Drive版履歴IDや`modified_time`で代用しない。
- Google Drive API v3の`files.version`はGoogle公式で**単調増加**と記載。`drive.metadata.readonly`は**ファイル内容へのアクセスを許さないメタデータ専用スコープ**。根拠： https://developers.google.com/workspace/drive/api/reference/rest/v3/files 、 https://developers.google.com/workspace/drive/api/guides/file-metadata
- 既存の`supplier-docs-reader`専用WIFプロバイダーの**実IAM読み取りと実OIDC交換は未検証**。AWS/Amazon SP-APIの本番用Google IDを流用しない。
- Private GitHub workflow設置やIAMの拡大を本開発では実施していない。公開開発GitHub Actionsへ`id-token:write`を追加していない。
- WIF認証を取得したホストの本人認証・ファイルの閲覧権を**アプリ層で毎回確認**する。版番号やCLIの`--confirm-readonly`は**本人認証の代わりではない**。
- Google Cloud/Drive API側は設定・クォータ・課金条件に依存する。ここでは新有料サービスを導入せず、**費用が必ずゼロになる保証はしない**。

## 検証内容

- `test_supplier_drive_version_bridge.py`：Drive v3 metadata-onlyサービスのWIF ADC scope、`files.get`の3フィールド指定、異なるID／MIME／不正version拒否、raw例外の機密非表示を**架空データのみ**で確認。
- `test_supplier_manual_drive_version_probe.py`：試験用1ファイル選択と明示承認、元ファイルID・版番号・OAuth詳細を出さない成功／停止レスポンス、接続失敗時の安全停止を**架空データのみ**で確認。
- 既存のメーカーデータ解析・ページ検索とAmazonとは無関係なGitHub CIで回帰テスト実施。**実ファイルID・メーカーの明細やGoogle認証トークンを公開CIへ渡していない**。

## 次の優先作業

1. 所有者の許可のもと、**既存専用WIF/Readerの実設定とPrivateリポジトリ権限・課金停止条件**を、すでに用意された`manual_wif_preflight_cli`等の**読み取り専用**の方法で確認する。
2. 条件が揃った場合のみ、Private手動1回・対象1資料だけのversion取得を実行し、成功なら`version`付きで実メーカー資料の**バッチ間継続検索**を検証する。
3. その後、本人専用の恒常的実行UIと、112社の資料索引への適用を進める。Claudeは将来互換のみで未導入。
