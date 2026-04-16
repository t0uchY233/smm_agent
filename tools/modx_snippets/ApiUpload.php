<?php
/**
 * Сниппет ApiUpload — API для загрузки изображений в MODX
 * Вызывается из ресурса с типом содержимого JSON
 *
 * Принимает одно или несколько изображений (base64),
 * сохраняет в assets/blog/YYYY/MM/, возвращает URL.
 *
 * === УСТАНОВКА В MODX ===
 * 1. Создать сниппет «ApiUpload» с этим кодом
 * 2. Создать ресурс (например /api-upload.html)
 *    - Тип содержимого: JSON
 *    - Шаблон: пустой
 *    - Содержимое: [[!ApiUpload]]
 * 3. Убедиться, что папка assets/blog/ существует и доступна на запись
 * 4. В php.ini: post_max_size >= 16M, upload_max_filesize >= 16M
 *
 * === ФОРМАТ ЗАПРОСА ===
 * POST /api-upload.html
 * Header: X-API-Key: <ключ>
 * Body (JSON):
 * {
 *   "images": [
 *     {
 *       "filename": "museum.jpg",          // опционально, будет сгенерировано если нет
 *       "data": "/9j/4AAQSkZJRg...",       // base64 без префикса data:...
 *       "content_type": "image/jpeg"        // опционально, определится автоматически
 *     }
 *   ]
 * }
 *
 * === ФОРМАТ ОТВЕТА ===
 * HTTP 201:
 * {
 *   "success": true,
 *   "uploaded": [
 *     {
 *       "filename": "museum.jpg",
 *       "url": "https://veselkov.me/assets/blog/2026/04/museum.jpg",
 *       "path": "assets/blog/2026/04/museum.jpg",
 *       "size": 219792
 *     }
 *   ],
 *   "count": 1
 * }
 */

// === НАСТРОЙКИ ===
$apiKey      = 'NiyWVKGUmi3VQfExifLiD6pZQG_9vTID';
$uploadBase  = 'assets/blog/';         // относительно MODX_BASE_PATH
$maxFileSize = 10 * 1024 * 1024;       // 10 МБ на файл
$maxFiles    = 20;                      // макс. файлов за один запрос
$allowedTypes = [
    'image/jpeg' => 'jpg',
    'image/png'  => 'png',
    'image/webp' => 'webp',
    'image/gif'  => 'gif',
];

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
if (empty($input['images']) || !is_array($input['images'])) {
    http_response_code(400);
    return json_encode(['success' => false, 'error' => 'Поле images обязательно (массив)'], JSON_UNESCAPED_UNICODE);
}

if (count($input['images']) > $maxFiles) {
    http_response_code(400);
    return json_encode(['success' => false, 'error' => "Максимум {$maxFiles} файлов за запрос"], JSON_UNESCAPED_UNICODE);
}

// === Подготовка директории YYYY/MM ===
$datePath = date('Y') . '/' . date('m') . '/';
$fullDir  = MODX_BASE_PATH . $uploadBase . $datePath;

if (!is_dir($fullDir)) {
    if (!mkdir($fullDir, 0755, true)) {
        http_response_code(500);
        return json_encode(['success' => false, 'error' => 'Не удалось создать директорию'], JSON_UNESCAPED_UNICODE);
    }
}

// === Загрузка файлов ===
$uploaded = [];
$errors   = [];

foreach ($input['images'] as $i => $img) {
    // Проверка наличия данных
    if (empty($img['data'])) {
        $errors[] = "Изображение #{$i}: отсутствует поле data";
        continue;
    }

    // Декодирование base64
    // Убираем data:image/...;base64, префикс если есть
    $b64 = $img['data'];
    if (strpos($b64, 'base64,') !== false) {
        $b64 = substr($b64, strpos($b64, 'base64,') + 7);
    }

    $binary = base64_decode($b64, true);
    if ($binary === false) {
        $errors[] = "Изображение #{$i}: невалидный base64";
        continue;
    }

    // Проверка размера
    $size = strlen($binary);
    if ($size > $maxFileSize) {
        $sizeMB = round($size / 1024 / 1024, 1);
        $errors[] = "Изображение #{$i}: размер {$sizeMB} МБ превышает лимит";
        continue;
    }

    // Определение типа файла
    $finfo = new finfo(FILEINFO_MIME_TYPE);
    $mimeType = $finfo->buffer($binary);

    if (!isset($allowedTypes[$mimeType])) {
        $errors[] = "Изображение #{$i}: тип {$mimeType} не поддерживается";
        continue;
    }

    $ext = $allowedTypes[$mimeType];

    // Формирование имени файла
    if (!empty($img['filename'])) {
        // Очистка имени: только латиница, цифры, дефисы, точки
        $name = preg_replace('/[^a-zA-Z0-9._-]/', '', pathinfo($img['filename'], PATHINFO_FILENAME));
        if (empty($name)) {
            $name = 'img-' . uniqid();
        }
    } else {
        $name = 'img-' . uniqid();
    }

    $filename = $name . '.' . $ext;

    // Уникальность: если файл существует — добавить суффикс
    $finalPath = $fullDir . $filename;
    if (file_exists($finalPath)) {
        $filename = $name . '-' . substr(uniqid(), -5) . '.' . $ext;
        $finalPath = $fullDir . $filename;
    }

    // Запись файла
    if (file_put_contents($finalPath, $binary) === false) {
        $errors[] = "Изображение #{$i}: ошибка записи файла";
        continue;
    }

    // Формирование URL
    $relativePath = $uploadBase . $datePath . $filename;
    $url = $modx->getOption('site_url') . $relativePath;

    $uploaded[] = [
        'filename' => $filename,
        'url'      => $url,
        'path'     => $relativePath,
        'size'     => $size,
    ];
}

// === Ответ ===
if (empty($uploaded) && !empty($errors)) {
    http_response_code(400);
    return json_encode([
        'success' => false,
        'errors'  => $errors,
    ], JSON_UNESCAPED_UNICODE);
}

$response = [
    'success'  => true,
    'uploaded' => $uploaded,
    'count'    => count($uploaded),
];

if (!empty($errors)) {
    $response['warnings'] = $errors;
}

http_response_code(201);
return json_encode($response, JSON_UNESCAPED_UNICODE);
