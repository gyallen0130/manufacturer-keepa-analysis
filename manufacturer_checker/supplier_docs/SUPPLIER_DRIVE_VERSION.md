# Google Drive v3 強い版番号による安全なメーカー資料の継続検索

更新：2026-11-09 JST / 開発用Draft PR #1、main未マージ

## 結論

Google Drive API v3 の files リソースには **version（int64を表す十進数文字列）** が存在し、「Googleのサーバー上でファイルに対して行われたすべての変更で単調増加する」特性が公式に記載されている。

- Google公式: https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- Google公式の変更履歴説明: https://developers.google.com/workspace/drive/api/guides/change-overview
- Google公式の revisions.list 制限: https://developers.google.com/workspace/drive/api/reference/rest/v3/revisions/list

**現状接続の制約**：ChatGPTで利用できる Google Drive `get_file_metadata` に対し、`fields=id,name,mimeType,modifiedTime,version,headRevisionId` を明示して実行したが、現在のコネクタの整形済み返り値には `version` 項目が現れなかった。 `modified_time` はある。Googleの revisions.list 相当の接続では現行revision IDが得られたが、Google Workspace の改訂履歴は統合されることがあり、任意の編集時に必ず変更を検出できる**強い版トークンとして採用しない**。

よって、**実データを用いたバッチまたぎの継続検索は、このChatGPTコネクタだけでは実運用しない**。安全に必要な`version`を返せる、アクセス権を確認済みの raw Google Drive v3 files.get クライアントが接続できるまで停止する。

## 新しい実装

- `supplier_drive_version.py`：厳格なファイル版番号アダプター。認証済み外部コネクタから **`files.get(fileId=..., fields='id,mimeType,version')`** を呼ぶ契約。
- `make_drive_v3_version_adapter(authenticated_raw_files_get)` のコールバックを、既存 `scan_next_selected_supplier_sheet(..., get_source_revision=adapter)` へ渡す。
- `strict_drive_v3_version` は **raw Google JSON**の `id`、`mimeType`、`version` の3キーを検査する。選択したファイルIDと一致しない、ネイティブのGoogle Sheetsでない、版番号が欠ける、数値精度を損なうJS数値型、ゼロ、負数、先頭ゼロ付き、int64範囲外、余分なフィールドを含む場合は停止。
- アダプターの証拠は`{'spreadsheet_id':..., 'revision_kind':'google_drive_v3_monotonic_file_version', 'version':'123'}`。長文書スキャナーが**この厳密な種類と数値を必須**にし、ハッシュ化して本人専用カーソルと突合する。
- `modifiedTime`、`currentRevisionId`、`previousRevisionId`、接続元の任意の`revision`文字列は、**黙って代用しない**。
- ネットワーク例外は内部情報を破棄して一般的な例外に変換する。元のOAuthトークン・商品情報・ファイルIDを公開ログに出さない。

## Pythonホスト側の契約（実行コード例・公開可能な架空ID）

```python
from supplier_docs.supplier_drive_version import (
    make_drive_v3_version_adapter,
)
from supplier_docs.supplier_scan_continuation import (
    scan_next_selected_supplier_sheet,
)

def trusted_raw_files_get(*, file_id, fields):
    # 接続済みの本人OAuth認証・資料閲覧権を実際に検証した
    # PRIVATE実行環境のGoogle Drive v3クライアントだけが実装。
    # client.files().get(fileId=file_id,fields=fields).execute()
    # を行って3キーのraw辞書を返す。API失敗なら必ず例外。
    raise NotImplementedError("requires authenticated Google Drive v3 client")

version_reader = make_drive_v3_version_adapter(trusted_raw_files_get)
# scan_next_selected_supplier_sheet(...,
#     get_source_revision=version_reader, ...)
```

`NotImplementedError` のままの例は**実運用コードではない**。ChatGPTの既存コネクタは`version`を返さないので、その整形済みメタデータをこの引数に渡しても失敗するように設計している。

## 強い版番号を使う場合でも必要な安全管理

- 毎回、利用者本人とGoogle資料への閲覧権・可視タブを**ホスト側**で確認する。Pythonのフラグや版番号だけでは本人認証・認可されない。
- バッチ読取前後にraw versionを再取得し、**同一である場合だけ**そのバッチ結果を採用。前バッチの版番号と今回の版番号が異なる場合は「原本が変更されたため最初からやり直し」とする。履歴混合はしない。
- 見出しと前回最終物理行のハッシュも照合する。カーソルはPRIVATEメモリ／暗号化保存でのみ使用し、署名済み認可トークンと混同しない。
- Googleの版番号が増えても、変更が商品の列以外だった可能性はあるが、誤検索防止を優先して**すべての変更で停止**する。
- 他社の資料・未読のシート・残りの行について商品が存在しないとは断定しない。
- 新有料サービス、IAM、Secrets、GitHub本番workflowは今回設定していない。Claudeは未導入。Google Driveの権限や原本資料は書き換えていない。

## 2026-11-09 の検証と残タスク

**実Google接続確認**
1. 以前より閲覧を確認済みのGoogle Sheetsで、`get_file_metadata`に`version`をfields指定しても、結果の正規化されたスキーマには`version`が表示されないことを確認。
2. 同ファイルのrevision一覧は5件と現行IDが取得できた。ただし **revision IDでは更新検知を保証しない**。
3. Google公式仕様を照合。v3 files.version は単調増加だが、`headRevisionId`は主にバイナリファイル向けであり、ネイティブSheetsに安易に代用しない。

**GitHub CI**
- `test_supplier_drive_version.py` に合成テスト**11件**追加。正常版番号、最大int64、正しいfiles.get fields、欠落・不正型、他ファイル、他MIME、余剰キー、現行ChatGPTコネクタのversion非表示、timestamp/revisions IDの混入拒否、API例外の秘密非表示、スキャナー再開時の版変更停止など。
- `test_supplier_scan_continuation.py`の既存17テストも、任意の文字列ではなく**厳格なGoogle v3ファイル版番号証拠**で実行するよう改修。
- **GitHub Actionsの公開CIで728件のPythonテスト・3検証ジョブすべて成功**。実商品値、版番号、原本ID、トークンはコミットしていない。

**次の工程**
1. 今のChatGPT標準コネクタでraw版番号が取得できないため、Google IAMや新課金を変えずに**既存のGoogle接続から安全にraw files.get(version)を提供できるホスト**を検証する。
2. ホストが利用できる場合のみ、版番号をバッチ間で比較する、実メーカーGoogle Sheetsの**読取専用**の再開検索E2Eを行う。
3. 112社の対象管理・Private検索UI・GitHub→Google WIF Reader実認証とアクセス管理を、セキュリティ・コストレビュー後に進める。
