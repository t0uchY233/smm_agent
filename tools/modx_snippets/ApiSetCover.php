<?php
/**
 * Сниппет ApiSetCover — установка обложки статьи через miniShop2
 *
 * POST /api-set-cover.html
 * X-API-Key: <ключ>
 * {"resource_id": 680, "image_data": "<base64>"}
 * или {"resource_id": 680, "image_url": "https://...cover.png"}
 */

$apiKey = 'NiyWVKGUmi3VQfExifLiD6pZQG_9vTID';

// === Только POST ===
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    return json_encode(['success' => false, 'error' => 'POST only'], JSON_UNESCAPED_UNICODE);
}

// === API-ключ ===
$key = isset($_SERVER['HTTP_X_API_KEY']) ? $_SERVER['HTTP_X_API_KEY'] : '';
$input = json_decode(file_get_contents('php://input'), true);
if (empty($key) && isset($input['api_key'])) { $key = $input['api_key']; }
if (empty($key) || $key !== $apiKey) {
    http_response_code(401);
    return json_encode(['success' => false, 'error' => 'Неверный API-ключ'], JSON_UNESCAPED_UNICODE);
}

if (empty($input['resource_id'])) {
    http_response_code(400);
    return json_encode(['success' => false, 'error' => 'resource_id обязателен'], JSON_UNESCAPED_UNICODE);
}
$resourceId = (int)$input['resource_id'];

// === Проверка ресурса ===
$resource = $modx->getObject('modResource', $resourceId);
if (!$resource) {
    http_response_code(404);
    return json_encode(['success' => false, 'error' => "Ресурс {$resourceId} не найден"], JSON_UNESCAPED_UNICODE);
}

// === Получение изображения ===
$imageData = null;
$extension = 'png';

if (!empty($input['image_data'])) {
    $b64 = $input['image_data'];
    if (strpos($b64, 'base64,') !== false) {
        $b64 = substr($b64, strpos($b64, 'base64,') + 7);
    }
    $imageData = base64_decode($b64, true);
    $finfo = new finfo(FILEINFO_MIME_TYPE);
    $mimeType = $finfo->buffer($imageData);
    $extMap = ['image/jpeg' => 'jpg', 'image/png' => 'png', 'image/webp' => 'webp'];
    $extension = isset($extMap[$mimeType]) ? $extMap[$mimeType] : 'png';
} elseif (!empty($input['image_url'])) {
    $imageData = @file_get_contents($input['image_url']);
    if ($imageData === false) {
        http_response_code(400);
        return json_encode(['success' => false, 'error' => 'Не удалось скачать изображение'], JSON_UNESCAPED_UNICODE);
    }
    $pathInfo = pathinfo(parse_url($input['image_url'], PHP_URL_PATH));
    $extension = isset($pathInfo['extension']) ? strtolower($pathInfo['extension']) : 'png';
} else {
    http_response_code(400);
    return json_encode(['success' => false, 'error' => 'Нужен image_data или image_url'], JSON_UNESCAPED_UNICODE);
}

// === Авторизация ===
$modx->setOption('session_enabled', false);
$modx->getService('session', 'modSessionHandler');
$modx->user = $modx->getObject('modUser', array('username' => 'ulkin'));
$modx->user->addSessionContext('mgr');

// === Сохранение файла ===
$productsDir = MODX_BASE_PATH . 'assets/images/products/' . $resourceId . '/';
if (!is_dir($productsDir)) { mkdir($productsDir, 0755, true); }
$filename = 'cover.' . $extension;
$filePath = $productsDir . $filename;
file_put_contents($filePath, $imageData);

// === Миниатюры через GD ===
$thumbSizes = array('120x90', '360x270', '650x488');
foreach ($thumbSizes as $size) {
    list($w, $h) = explode('x', $size);
    $w = (int)$w; $h = (int)$h;
    $thumbDir = $productsDir . $size . '/';
    if (!is_dir($thumbDir)) { mkdir($thumbDir, 0755, true); }

    $srcImage = null;
    if (in_array($extension, ['jpg', 'jpeg'])) { $srcImage = @imagecreatefromjpeg($filePath); }
    elseif ($extension === 'png') { $srcImage = @imagecreatefrompng($filePath); }
    elseif ($extension === 'webp') { $srcImage = @imagecreatefromwebp($filePath); }

    if ($srcImage) {
        $srcW = imagesx($srcImage); $srcH = imagesy($srcImage);
        $ratio = max($w / $srcW, $h / $srcH);
        $newW = (int)ceil($srcW * $ratio); $newH = (int)ceil($srcH * $ratio);
        $offsetX = (int)(($newW - $w) / 2); $offsetY = (int)(($newH - $h) / 2);
        $thumb = imagecreatetruecolor($w, $h);
        if ($extension === 'png') { imagealphablending($thumb, false); imagesavealpha($thumb, true); }
        imagecopyresampled($thumb, $srcImage, -$offsetX, -$offsetY, 0, 0, $newW, $newH, $srcW, $srcH);
        $tp = $thumbDir . $filename;
        if (in_array($extension, ['jpg', 'jpeg'])) { imagejpeg($thumb, $tp, 90); }
        elseif ($extension === 'png') { imagepng($thumb, $tp, 8); }
        elseif ($extension === 'webp') { imagewebp($thumb, $tp, 90); }
        imagedestroy($thumb); imagedestroy($srcImage);
    }
}

// === Относительные пути ===
$relImage = 'assets/images/products/' . $resourceId . '/' . $filename;
$relThumb = 'assets/images/products/' . $resourceId . '/650x488/' . $filename;

// === Медиа-источник miniShop2 ===
$sourceId = (int)$modx->getOption('ms2_product_source_default', null, 1);

// ================================================================
// SQL через $modx->prepare()
// ================================================================

$prefix = $modx->getOption('table_prefix', null, 'modx_');
$prodTable = $prefix . 'ms2_products';
$fileTable = $prefix . 'ms2_product_files';
$uid = (int)$modx->user->get('id');

// --- 1. msProductData: проверить/создать/обновить ---
$stmt = $modx->prepare("SELECT id FROM {$prodTable} WHERE id = ?");
$stmt->execute(array($resourceId));
$existing = $stmt->fetch(PDO::FETCH_ASSOC);

if ($existing) {
    $stmt = $modx->prepare("UPDATE {$prodTable} SET image = ?, thumb = ? WHERE id = ?");
    $stmt->execute(array($relImage, $relThumb, $resourceId));
} else {
    $stmt = $modx->prepare("INSERT INTO {$prodTable} (id, source, image, thumb, price, old_price, weight, article, vendor, made_in, color, size, tags, new, favorite, popular) VALUES (?, ?, ?, ?, 0, 0, 0, '', '', '', '', '', '', 0, 0, 0)");
    $stmt->execute(array($resourceId, $sourceId, $relImage, $relThumb));
}

// --- 2. msProductFile: очистить и создать ---
$stmt = $modx->prepare("DELETE FROM {$fileTable} WHERE product_id = ?");
$stmt->execute(array($resourceId));

$relPath = $resourceId . '/';
$fileUrl = '/assets/images/products/' . $resourceId . '/' . $filename;
$hash = sha1_file($filePath);
$imgSize = filesize($filePath);
$imgInfo = @getimagesize($filePath);
$props = json_encode([
    'size' => $imgSize,
    'width' => $imgInfo ? $imgInfo[0] : 0,
    'height' => $imgInfo ? $imgInfo[1] : 0,
    'bits' => $imgInfo && isset($imgInfo['bits']) ? $imgInfo['bits'] : 8,
    'mime' => $imgInfo ? $imgInfo['mime'] : 'image/png',
]);
$coverName = pathinfo($filename, PATHINFO_FILENAME);
$stmt = $modx->prepare("INSERT INTO {$fileTable} (product_id, source, parent, name, description, path, file, type, createdon, createdby, `rank`, url, properties, hash) VALUES (?, ?, 0, ?, '', ?, ?, 'image', NOW(), ?, 0, ?, ?, ?)");
$ok = $stmt->execute(array($resourceId, $sourceId, $coverName, $relPath, $filename, $uid, $fileUrl, $props, $hash));

if (!$ok) {
    http_response_code(500);
    return json_encode(['success' => false, 'error' => 'Ошибка записи msProductFile', 'sql_error' => $stmt->errorInfo()], JSON_UNESCAPED_UNICODE);
}

// Получаем ID главного файла
$stmt = $modx->prepare("SELECT MAX(id) FROM {$fileTable} WHERE product_id = ? AND parent = 0");
$stmt->execute(array($resourceId));
$mainFileId = (int)$stmt->fetchColumn();

// Миниатюры
foreach ($thumbSizes as $size) {
    $sRelPath = $resourceId . '/' . $size . '/';
    $sUrl = '/assets/images/products/' . $resourceId . '/' . $size . '/' . $filename;
    $thumbPath = $productsDir . $size . '/' . $filename;
    $tSize = @filesize($thumbPath) ?: 0;
    $tInfo = @getimagesize($thumbPath);
    $tProps = json_encode([
        'size' => $tSize,
        'width' => $tInfo ? $tInfo[0] : 0,
        'height' => $tInfo ? $tInfo[1] : 0,
        'bits' => $tInfo && isset($tInfo['bits']) ? $tInfo['bits'] : 8,
        'mime' => $tInfo ? $tInfo['mime'] : 'image/png',
    ]);
    $stmt = $modx->prepare("INSERT INTO {$fileTable} (product_id, source, parent, name, description, path, file, type, createdon, createdby, `rank`, url, properties, hash) VALUES (?, ?, ?, ?, '', ?, ?, 'image', NOW(), ?, 0, ?, ?, ?)");
    $stmt->execute(array($resourceId, $sourceId, $mainFileId, $size, $sRelPath, $filename, $uid, $sUrl, $tProps, $hash));
}

// --- 3. updateProductImage через xPDO ---
$productData = $modx->getObject('msProductData', $resourceId);
if ($productData && method_exists($productData, 'updateProductImage')) {
    $productData->updateProductImage();
}

// --- 4. Очистка кеша ---
$modx->cacheManager->refresh();

// === Ответ ===
$siteUrl = $modx->getOption('site_url');
http_response_code(201);
return json_encode([
    'success'     => true,
    'resource_id' => $resourceId,
    'image_url'   => $siteUrl . $relImage,
    'thumb_url'   => $siteUrl . $relThumb,
    'message'     => 'Обложка установлена',
], JSON_UNESCAPED_UNICODE);
