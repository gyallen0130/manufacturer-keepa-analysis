# Google Driveメーカー資料：検索ヒットの非公開閲覧（開発中）

更新：2026-11-09 JST

## 目的と今回の実装

既存のExcel＋Google Sheets共通正規化・JAN/ASIN検索は、公開用には**匿名件数のみ**を返す。取引先商品の実務調査には「どの資料の何行目か」を見る必要があるため、利用者に限定した**別入口**を追加した。

- 既定：`connector_mixed_one_shot.inspect_private_connector_mixed()` は**匿名件数のみ**。変更していない。機密の原本パス・Google ID・JAN・商品名は戻り値に含まれない。
- 明示操作：`connector_mixed_one_shot.inspect_private_connector_mixed_for_review()` は、外部の認可済み実行環境が**元ファイルのアクセス権・受信先セッション・本人による詳細閲覧操作・公開ログなし**を確認したことを前提に、`prepare_selected_private_hit_review()`で非公開詳細を組み立てる。
- **重要**：このPython関数は**認証・本人確認・権限確認の実装ではない**。呼出元の確認済みフラグは外部チェックの宣言にすぎず、悪意ある呼出元を拒否するセキュリティ境界にならない。必ず認証済みChatGPT/Drive等の**同一利用者の非公開環境**でだけ呼び、返り値をGitHub、CI、公開ログ、他利用者向けUI、メール本文へ出さない。
- 外部APIや認証トークンの取得、フォルダ自動巡回、ファイルの変更、原価計算、発注はしない。

## 対象情報と明示的に出さない情報

**非公開の戻り値**に含めるもの：
- 一致した商品名、メーカー名（**文書に値があった場合だけ**）、型番、JAN候補、ASIN候補
- 呼出元が明示した取引先ラベル（本人確認・法人名の正当性をプログラムが証明するものではない）
- 元Excelの相対ファイルパスまたは元Google SheetのURL、タブ名、**物理行番号**
- `JAN_NUMERIC_CELL`等の確認警告と、あくまで候補であるという状態
- 選択済み資料タブ数、検索一致総数、詳細表示件数、表示打切りの有無

**含めないもの**：仕入原価、仕入価格、税率、発注単位、メモ、計算式内容、非一致行、OAuthトークン、元ファイルの絶対パス、実際の仕入判断。

**範囲**：すでに承認されたExcel＋Sheets合わせて**1〜5タブ**、各**A1:O40**、詳細表示は**最大20件**。100件の検索候補があっても、限界を超えた部分は打切りを明示する。**未選択のメーカーや112社すべてを検索したと主張しない**。

### 非公開Python環境での使用例（架空）

```python
from supplier_docs.connector_mixed_one_shot import (
    inspect_private_connector_mixed_for_review,
)

# 実行前にChatGPT等のアプリ層で、現在の利用者の認証、
# 対象Drive資料の閲覧権限と、非公開表示先を実際に確認する。
verified_context = {
    "source_access_checked": True,
    "private_recipient_checked": True,
    "private_display_requested": True,
    "no_public_logging": True,
}
# この辞書の真偽値自体がGoogleの認可を保証するわけではない。
# approved_excel_manifest と approved_sheet_manifest は
# 許可されたPRIVATE環境に存在する取得済みデータを指定。
private_review = inspect_private_connector_mixed_for_review(
    root_dir=private_excel_directory,
    excel_manifest=approved_excel_manifest,
    connector_sheet_manifest=approved_sheet_manifest,
    search={"field": "asin", "query": requested_asin},
    reviewer_context=verified_context,
    source_labels=["Excel取引先（確認済み）", "Sheets取引先（確認済み）"],
    max_hits=20,
)
# 機密のprivate_reviewをprint/log/JSON保存/GitHub転送しない。
# 確認済みの本人だけに、許可された非公開画面で必要項目を表示する。
```

`source_labels`は**選択タブと同数**で、元データと照合した上で指定する。ラベルなしでも相対ファイルパス／タブ名と原本URLから参照できる。ラベルを設定しただけでメーカーの法的同一性が証明されるわけではない。

## 原本位置と警告の扱い

- Google Sheets：元のGoogle Sheet URL、タブ、物理行番号を返す。編集リンクの生成やセルの編集は行わない。
- Excel：許可済みのPrivateローカル相対ファイルパス、タブ、物理行番号を返す。Driveへ自動書戻ししない。
- JANが数値型なら、`JAN_NUMERIC_CELL`の警告を表示する。先頭0が欠落している可能性を残した**候補**とし、Amazonの販売単位との一致を保証しない。
- 複数候補ASINは`asin_candidates`をすべて保持する。勝手に1件へ確定しない。
- `native_export_xlsx`のSheetsデータでは数式の忠実性・価格条件を保証しない。価格関連の戻り値は出さない。

## 安全性と検証

- 表示要求が無い・4項目の外部確認済み宣言が不足している場合、Excel原本を開く前に拒否。
- 検索条件を**非公開メモリ内で再検索**し、保存済みヒットポインタと突合してから表示。古い検索や別商品へのポインタのすり替えは拒否。
- Excelの原本パスとパーサーの文書ID／タブが一致することを検証。古い匿名正規化結果に原本パスが無い場合、**匿名検索は続行可能だが、非公開詳細表示だけ拒否**して推測パスを返さない。
- 原本や認証情報はGitHubへ送信せず、`include_sensitive=False`を維持。
- `test_supplier_private_hit_review.py`で**架空データ14テスト**を実装。非公開フラグ不備、JAN/ASIN候補、物理行、ラベル、20件上限、価格非表示、検索結果すり替え、出典すり替え、数式の非表示、元ファイル不変などを検査。

## 未完成と次工程

今回完成したのは**非公開Python関数からの詳細データ生成**であり、利用者がワンクリックで使える認証付き画面の開設やGitHubからの自動Drive参照ではない。

1. **ChatGPT/Driveの認証済み呼出元からこの関数を起動し、非公開の本人セッションだけへ表示する実運用アダプター**を整備する。実データで表示動作とプライバシーを再確認する。
2. 次に112社のメーカー・卸問屋フォルダから、許可済みの資料を**検索対象として選択・更新**する運用経路を整える。
3. 最後にGitHub Actions→Google WIF→専用Readerの実認証を、費用とアクセス権を確認してから検討する。**現時点では設定・Secrets・IAMを変更しない**。

Claudeは将来的な呼出元と見なし、特定のモデルSDKに依存しないPython関数を使用。Claudeのサービス導入や課金は行わない。
