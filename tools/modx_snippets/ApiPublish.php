<?php
/**
 * Сниппет ApiPublish — API для публикации статей в MODX
 * Вызывается из ресурса с типом содержимого JSON
 *
 * ВАЖНО: class_key = msProduct, чтобы статьи корректно отображались
 * на главной странице и в RSS-ленте (miniShop2)
 */
// === НАСТРОЙКИ ===
$apiKey = 'NiyWVKGUmi3VQfExifLiD6pZQG_9vTID';
$defaultParent = 1;    // ID "Главная блога"
$defaultTemplate = 8;  // ID шаблона статей
$autoPublish = true;

// === Только POST ===
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    return json_encode(['success' => false, 'error' => 'Только POST-запросы'], JSON_UNESCAPED_UNICODE);
}

// === Проверка API-ключа ===
$key = isset($_SERVER['HTTP_X_API_KEY']) ? $_SERVER['HTTP_X_API_KEY'] : '';
$input = json_decode(file_get_contents('php://input'), true);

if (empty($key) && isset($input['api_key'])) {
    $key = $input['api_key'];
    unset($input['api_key']);
}

if (empty($key) || $key !== $apiKey) {
    http_response_code(401);
    return json_encode(['success' => false, 'error' => 'Неверный API-ключ'], JSON_UNESCAPED_UNICODE);
}

// === Проверка данных ===
if (empty($input) || !is_array($input)) {
    http_response_code(400);
    return json_encode(['success' => false, 'error' => 'Пустое тело запроса'], JSON_UNESCAPED_UNICODE);
}

if (empty($input['pagetitle'])) {
    http_response_code(400);
    return json_encode(['success' => false, 'error' => 'Поле pagetitle обязательно'], JSON_UNESCAPED_UNICODE);
}

// === Генерация alias ===
$alias = '';
if (!empty($input['alias'])) {
    $alias = $input['alias'];
} else {
    $alias = $modx->filterPathSegment($input['pagetitle']);
    if (empty($alias)) {
        $alias = 'article-' . time();
    }
}

$parent = isset($input['parent']) ? (int)$input['parent'] : $defaultParent;

// Проверяем уникальность alias
$existing = $modx->getObject('modResource', array('alias' => $alias, 'parent' => $parent));
if ($existing) {
    $alias .= '-' . time();
}

// === Собираем данные ресурса ===
$resourceData = array(
    'pagetitle'    => $input['pagetitle'],
    'longtitle'    => isset($input['longtitle']) ? $input['longtitle'] : '',
    'description'  => isset($input['description']) ? $input['description'] : '',
    'introtext'    => isset($input['introtext']) ? $input['introtext'] : '',
    'alias'        => $alias,
    'parent'       => $parent,
    'template'     => isset($input['template']) ? (int)$input['template'] : $defaultTemplate,
    'published'    => isset($input['published']) ? (int)$input['published'] : ($autoPublish ? 1 : 0),
    'hidemenu'     => isset($input['hidemenu']) ? (int)$input['hidemenu'] : 0,
    'searchable'   => 1,
    'cacheable'    => 1,
    'content_type' => 1,
    'class_key'    => 'msProduct',   // ИСПРАВЛЕНО: было modDocument, из-за чего статьи не появлялись на главной и ломался [msOptions]
    'context_key'  => 'web',
);

// === Авторизация под админом для создания ресурса ===
$modx->setOption('session_enabled', false);
$modx->getService('session', 'modSessionHandler');
$modx->user = $modx->getObject('modUser', array('username' => 'ulkin'));
$modx->user->addSessionContext('mgr');

// === Создание ресурса через процессор ===
// Используем процессор msProduct для корректного создания товара miniShop2
$response = $modx->runProcessor('resource/create', $resourceData);

if ($response->isError()) {
    http_response_code(500);
    return json_encode([
        'success' => false,
        'error'   => 'Ошибка создания',
        'details' => $response->getAllErrors()
    ], JSON_UNESCAPED_UNICODE);
}

$obj = $response->getObject();
$resourceId = $obj['id'];

// === Контент ===
if (!empty($input['content'])) {
    $res = $modx->getObject('modResource', $resourceId);
    if ($res) {
        $res->setContent($input['content']);
        $res->save();
    }
}

// === TV-параметры ===
if (!empty($input['tvs']) && is_array($input['tvs'])) {
    $res = $modx->getObject('modResource', $resourceId);
    if ($res) {
        foreach ($input['tvs'] as $tvName => $tvValue) {
            $res->setTVValue($tvName, $tvValue);
        }
    }
}

// === URL ===
$url = $modx->makeUrl($resourceId, '', '', 'full');

http_response_code(201);
return json_encode([
    'success' => true,
    'id'      => (int)$resourceId,
    'url'     => $url,
    'alias'   => $alias,
    'message' => 'Статья успешно создана'
], JSON_UNESCAPED_UNICODE);
