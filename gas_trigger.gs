/**
 * 毎日深夜（例: 午前1時）に定期実行され、当日の9:00:00に一度だけ実行されるワンタイムトリガーを生成する関数。
 * ※この関数をGASのUIから「毎日 1:00〜2:00」の時間主導型トリガーに設定してください。
 */
function setTrigger() {
  const time = new Date();
  
  // 今日の9時00分00秒を指定
  time.setHours(9);
  time.setMinutes(0);
  time.setSeconds(0);
  
  // 既に9時を過ぎている場合は設定しない（念のため）
  if (time.getTime() <= new Date().getTime()) {
    Logger.log("既に9時を過ぎているため、本日のトリガーは設定しません。");
    return;
  }
  
  // 指定日時にトリガーを作成
  ScriptApp.newTrigger('triggerGitHubAction').timeBased().at(time).create();
  Logger.log(time.toLocaleString() + " にGitHub Actions起動トリガーをセットしました。");
}

/**
 * 9:00:00にワンタイムトリガーから呼び出され、GitHub Actionsをキックする関数。
 * 実行後に、自身を起動したワンタイムトリガーを削除します。
 */
function triggerGitHubAction() {
  // スクリプトプロパティから必要な環境変数を取得
  const props = PropertiesService.getScriptProperties();
  const githubToken = props.getProperty('GITHUB_PAT'); // GitHub Personal Access Token
  const owner = props.getProperty('REPO_OWNER');       // リポジトリオーナー名 (例: your-username)
  const repo = props.getProperty('REPO_NAME');         // リポジトリ名 (例: daily_news)
  const workflowId = 'daily_news.yml';                 // ワークフローファイル名
  
  if (!githubToken || !owner || !repo) {
    Logger.log("エラー: スクリプトプロパティ (GITHUB_PAT, REPO_OWNER, REPO_NAME) が設定されていません。");
    return;
  }
  
  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowId}/dispatches`;
  
  const payload = {
    "ref": "main" // 対象のブランチ名。必要に応じて変更してください。
  };
  
  const options = {
    "method": "post",
    "contentType": "application/json",
    "headers": {
      "Authorization": "Bearer " + githubToken,
      "Accept": "application/vnd.github.v3+json"
    },
    "payload": JSON.stringify(payload)
  };
  
  try {
    const response = UrlFetchApp.fetch(url, options);
    Logger.log("GitHub Actions triggered successfully. Status: " + response.getResponseCode());
  } catch (e) {
    Logger.log("Error triggering GitHub Actions: " + e.toString());
  }
  
  // 使い終わったワンタイムトリガーをお掃除する
  cleanUpTriggers('triggerGitHubAction');
}

/**
 * 指定された名前の関数を呼び出すトリガーを全て削除する補助関数。
 * @param {string} functionName - 削除対象の関数名
 */
function cleanUpTriggers(functionName) {
  const triggers = ScriptApp.getProjectTriggers();
  for (let i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === functionName) {
      ScriptApp.deleteTrigger(triggers[i]);
      Logger.log("削除したワンタイムトリガー: " + functionName);
    }
  }
}
