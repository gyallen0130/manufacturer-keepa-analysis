# 認証済みGoogle Sheets＋ローカルExcelの1回限りの共通横断検索

## 目的と現在の境界

2026-11-08：`authorized_mixed_probe.py`を開発ブランチに追加した。**利用者が用意した認証済み・読取専用のGoogle Sheets v4クライアント**と、許可済みのローカルExcel原本を、**同じPrivate Pythonプロセス**に渡して検索するための入口である。

このファイルは**認証・IAM設定・Googleログイン・トークン受渡し・Driveファイルの全件探索・新規サービス契約を行わない**。ChatGPTのGoogle Driveコネクタに接続できることは、このPythonプロセスが同じOAuth資格情報を持っていることを意味しない。

## 実行時の構成

```python
from supplier_docs.authorized_mixed_probe import inspect_authorized_mixed_sources
from supplier_docs.auth import build_readonly_sheets_service_from_wif_adc

# 事前にPrivate環境で用意した明示承認済みのmanifestだけを使う。
# どのmanifestにも生商品データや実Googleトークンを入れず、
# private searchの照会番号もCIログ・GitHubへ書かない。
result = inspect_authorized_mixed_sources(
    root_dir='/private/approved-excel',
    excel_manifest=private_excel_manifest,
    sheets_manifest=private_sheets_manifest,
    service_factory=build_readonly_sheets_service_from_wif_adc,
    search={'field': 'jan', 'query': private_requested_jan},
)
print(result['public_summary'])
print(result['public_search_summary'])
# 元のファイル名/原本行/候補番号等を含む
# result['private_normalized_docs'] / ['private_hits'] はログへ出さない。
```

**WIF認証の前提**：上記`build_readonly_sheets_service_from_wif_adc`は、外部で構築・レビュー済みの**専用Readerサービスアカウント**に限定して使用する。既存の認証側の条件（不変repo ID、workflow_ref、main／手動実行、Sheets readonly Scope、対象ファイルViewer）を変更しない。**このPythonライブラリ単独ではその安全性を証明できない**。プロダクションSP-API用認証を流用しない。

## 入力と安全な実行順序

1. ExcelとSheetsの**両方のマニフェストを認証より先に検証**（各ファイルID、タブ名、型、必要な限定見出し、検索条件をチェック）。
2. 両形式を合わせて**1～5タブのみ**。Excelは承認済みPrivateディレクトリの`.xlsx`／`.xlsm`のみ。Sheetsはメタデータで可視タブを確認し、各`A1:O40`のみ`FORMULA`モードで読む。
3. 先にExcelの限定読取を試み、**不存在・不正なローカルファイルの場合はGoogleクライアント生成やAPI通信に入らない**。
4. 次に外部から渡されたFactoryで読取専用Sheetsクライアントを生成し、既存の`sheets_multi_bridge`で限定解析。
5. `mixed_source_readonly`で**元のシート種別・物理行番号をPrivateで保持し、JAN/ASIN/POS/ITFを別々に検索**。**利益/発注を許可しない**。公開できるのは匿名件数だけ。

## 検証結果と未完了範囲

- [8件の新規合成データテスト](../tests/test_supplier_authorized_mixed_probe.py)：架空ExcelとモックSheets v4を同一呼出し内で処理し、JAN照合2件、原本行追跡、機密値の出力抑止、検索不正・ファイル不存在・6タブ超過時のGoogle APIへの先行アクセス禁止、原本不変を検証。
- 2026-11-08、**ChatGPTの接続済みGoogle Driveでワコーフーズ・井上のSheet A1:O40をFORMULA形式で限定読取**し、先頭行の見出し位置・セル型・数式の存在を匿名集計した（実データをGitHubへ転載しない）。
- 既存の[Google SheetsネイティブExcelエクスポート＋実ExcelのPrivate横断解析](https://github.com/gyallen0130/amazon-business-knowledge/blob/main/suppliers/pilots/row-labeled-pos-itf-real-e2e-and-mixed-search-2026-11-08.md)等は、**実Google Sheets v4 APIによるPython認証ではない**。
- **未実施**：`inspect_authorized_mixed_sources`を、権限が実際に設定されたGoogle Reader・許可済み実Excelで直接起動する最終E2E。現在のChatGPT Private実行環境には`GOOGLE_APPLICATION_CREDENTIALS`等の実認証情報が提供されていないため、WIFの認証接続まで完了したとは言わない。Google IAM、WIF、Secrets、SP-APIは今回変更していない。
- **次の最重要作業**：既存の専用Readerが利用できるPrivate実行環境で、同じマニフェストによる実Google API read-only＋実Excelの限定1回実行を検証し、匿名件数・APIの成功/失敗のみを記録。**追加費用を伴うサービス導入や無断権限変更はしない**。

