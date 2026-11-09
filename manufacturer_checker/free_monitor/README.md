# Google Apps Script：追加月額費用を避ける更新確認の試験版

**状態：開発用のソースコードと架空データによるテストのみ。実Google Driveアクセス・Apps Script設置・トリガー作成・メール送信・課金リソース作成は未実施です。**

## 目的と範囲

指定された Google Sheets **1〜20ファイルだけ**の `id / mimeType / version / modifiedTime / trashed` を、Drive API v3の `files.get` で読み、前回明示的に承認した基準点との差分**件数だけ**を返します。ファイル名、取引先名、卸値、商品本文は取得しません。フォルダ全体の列挙・検索や `Drive.Files.list` を呼びません。

既存のGitHub Actionsによる分析と組み合わせる構成の候補ですが、**現時点でGitHub Actionsへの転送や定期通知もありません**。生データは公開GitHubには書き込まない設計です。

## ファイル

- `SupplierCore.gs`：メタデータ・承認済みIDリストの保守的な検証、差分件数の計算。ネットワーク・保存処理なし。
- `SupplierMonitor.gs`：Apps Scriptの読み取り専用API呼び出し。手動の `previewApprovedSupplierUpdates()` は状態を書き換えません。
- `appsscript.json`：Drive API v3高度なサービスと `drive.metadata.readonly` **のみ**を宣言。無断でトリガーを作りません。
- `tests/monitor.test.cjs`：Node標準のテストランナーだけを利用。架空データで手動実行・差分・権限・エラー・機密情報非表示を検査。

## 本番導入前の重要な判断

Apps Scriptは、現在のColabの**専用サービスアカウントではなく、許可したGoogleユーザーの権限で動作**します。 `drive.metadata.readonly` はそのユーザーがアクセスできるDrive内のメタデータを広く読める可能性がある **制限付きOAuthスコープ** です。プログラムで読み取り対象をIDリストに制限しても、OAuthのアクセス権自体をID単位に狭めるものではありません。

**所有者の明示的な承認があるまで、既存のGoogleアカウントでこのスクリプトを認可したり、トリガーを設定したりしないでください。** 費用だけでなく、既存の専用SAによる限定共有と比較してプライバシー・最小権限を評価します。

## 将来の手動試運転手順（未実施）

1. 公開GitHubとは無関係の **Private Apps Scriptプロジェクト** を作成し、ソースの2つの `.gs` ファイルと `appsscript.json` を配置する。高度なDriveサービスv3を有効にする。標準Cloudプロジェクトを使う場合はDrive APIの有効化も必要。
2. **Private Script Properties**の `SUPPLIER_ALLOWLIST_JSON` に明示承認済みGoogle Sheets IDのJSON配列を保存する（例は架空の `["fake_sheet_abcdef123"]`）。**実IDは公開GitHub・チャットの共有ログに保存しない**。
3. `previewApprovedSupplierUpdates()` を実行すると、初回は `baselineRequired: true` の匿名件数だけが出る。ファイルID・商品名・価格はログに出さない。取得失敗・削除扱い・重複はすべて中断。
4. 最初の基準点を作る必要がある場合は、初回を「過去分は再解析しない基準点として受け入れる」と理解した上で、**一度だけ** `SUPPLIER_INIT_ACK` に `I_ACCEPT_INITIAL_BASELINE_NO_BACKFILL` を設定して `initializeSupplierMonitorBaselineOnce()` を手動実行する。基準点はScript Propertiesの9 KB以内で保存され、再初期化は拒否される。
5. 次回以降の `previewApprovedSupplierUpdates()` は変更件数だけを表示。**差分が見つかっても勝手に基準点を更新しない**ので、処理漏れ・重複を回避できる。更新を処理完了にするワークフローは別途検証するまで実装しない。

## 制限・リスク

- Script Propertiesはユーザー所有のスクリプトにひも付く保存先であり、**暗号化済みの専用データベースではない**。編集権限を持つ人は私的なIDや版情報を読める可能性がある。本文や価格は保存しない。
- 1件あたりのProperty文字列は9 KB上限。ファイル数20件を上限にしているが、メタデータの大きさと他のProperty利用状況により失敗し得る。保存失敗時は前の基準点を維持する。
- 1実行は6分以内、個人アカウントのトリガー合計90分/日などの割り当てがある。無料で安定運用できることはまだ実証していない。
- **現時点は手動のみ**。Scheduler、Trigger、GitHub Actions API連携、MailApp、購入、Amazon API、原本書き込み機能は存在しない。
- 運用化に際しては、漏洩リスク・既存の専用SA・無料枠・実行時間を再評価。新たな固定費や課金可能なサービスは所有者の明示承認なしで導入しない。

公式資料：
- https://developers.google.com/apps-script/advanced/drive
- https://developers.google.com/workspace/drive/api/reference/rest/v3/files/get
- https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- https://developers.google.com/apps-script/guides/services/quotas

## 自動テスト

```bash
node --test manufacturer_checker/free_monitor/tests/monitor.test.cjs
```

Nodeの標準機能だけを使い、ネットワークや実Googleデータは使いません。GitHub Actionsの既存PR CIで実行します。
