<?php
/**
 * Сниппет RssDzen — генерация RSS-ленты для Яндекс Дзена
 * Требования: https://dzen.ru/help/ru/website/rss-modify.html
 *
 * Вызов: [[!RssDzen]]
 * Размещается в ресурсе /in/feed.xml с Content-Type: text/xml
 */
@ini_set('display_errors', 0);
$output = '';
$limit = 50;          // Берём с запасом, фильтруем по длине контента
$minContentLen = 300; // Минимум символов текста для Дзена
$siteUrl = rtrim($modx->getOption('site_url'), '/');

// Дата отсечки: статьи до этой даты в RSS не попадают.
// Старые статьи остаются как есть, в Дзен идут только новые.
// ВАЖНО: createdon в MODX хранится как Unix timestamp (int),
// поэтому сравниваем тоже с timestamp, а не со строкой даты.
$cutoffDate = strtotime('2026-04-15 00:00:00'); // 1744668000

// Получаем ID всех дочерних категорий блога (parent=1, глубина 1)
$parentIds = $modx->getChildIds(1, 1);
if (empty($parentIds)) {
    return '';
}

$query = $modx->newQuery('modResource');
$query->where(array(
    'parent:IN'     => $parentIds,
    'published'      => 1,
    'deleted'        => 0,
    'createdon:>='   => $cutoffDate,
));
$query->sortby('createdon', 'DESC');
$query->limit($limit);

$resources = $modx->getCollection('modResource', $query);

$itemCount = 0;

foreach ($resources as $res) {
    $content = $res->getContent();
    $resourceId = $res->get('id');

    // --- Очистка контента для Дзена ---

    // 1. Заменяем YouTube iframe на plain ссылку (Дзен авто-конвертирует)
    $content = preg_replace_callback(
        '/<iframe[^>]*src=["\'](?:https?:)?\/\/(?:www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]+)[^"\']*["\'][^>]*><\/iframe>/i',
        function($m) {
            return '<p>https://www.youtube.com/watch?v=' . $m[1] . '</p>';
        },
        $content
    );

    // 2. Удаляем все остальные iframe
    $content = preg_replace('/<iframe[^>]*>.*?<\/iframe>/is', '', $content);

    // 3. Удаляем запрещённые теги (div, span, table, script, style, form, section, article, etc.)
    //    Оставляем содержимое, убираем только теги
    $forbiddenTags = array('div','span','table','tr','td','th','thead','tbody',
                           'script','style','form','input','select','textarea',
                           'header','footer','nav','section','article','aside','meta','link');
    foreach ($forbiddenTags as $tag) {
        // Удаляем открывающие и закрывающие теги, оставляя содержимое
        $content = preg_replace('/<\/?' . $tag . '(?:\s[^>]*)?\s*\/?>/i', '', $content);
    }

    // 3.5. Очищаем атрибуты с разрешённых тегов (class, data-*, id, style и пр.)
    //      Оставляем только href/src/alt/type/url на нужных тегах
    $content = preg_replace_callback(
        '/<([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^>]*?)?)(\s*\/?)>/s',
        function($m) {
            $tag = strtolower($m[1]);
            $attrs = $m[2];
            $selfClose = $m[3];
            // Разрешённые атрибуты по тегам
            $allowedAttrs = array(
                'a'      => array('href', 'title', 'target'),
                'img'    => array('src', 'alt', 'width', 'height'),
                'video'  => array('src', 'width', 'height'),
                'source' => array('src', 'type'),
            );
            if (!isset($allowedAttrs[$tag])) {
                // У остальных тегов атрибутов быть не должно
                return '<' . $tag . $selfClose . '>';
            }
            // Извлекаем только разрешённые атрибуты
            $kept = '';
            foreach ($allowedAttrs[$tag] as $attrName) {
                if (preg_match('/\b' . $attrName . '\s*=\s*("[^"]*"|\'[^\']*\'|\S+)/i', $attrs, $am)) {
                    $kept .= ' ' . $attrName . '=' . $am[1];
                }
            }
            return '<' . $tag . $kept . $selfClose . '>';
        },
        $content
    );

    // 4. Удаляем пустые параграфы
    $content = preg_replace('/<p>\s*<\/p>/i', '', $content);

    // 5. Trim
    $content = trim($content);

    // --- Проверяем длину текста без тегов ---
    $plainText = strip_tags($content);
    $plainText = trim(preg_replace('/\s+/', ' ', $plainText));
    if (mb_strlen($plainText, 'UTF-8') < $minContentLen) {
        // Пропускаем статьи без достаточного текста
        continue;
    }

    // --- Формируем поля item ---
    $title = htmlspecialchars($res->get('pagetitle'), ENT_XML1, 'UTF-8');
    $link = $siteUrl . '/' . ltrim($res->get('uri'), '/');

    // pubDate в RFC822
    $createdon = $res->get('createdon');
    if (is_numeric($createdon)) {
        $date = date('r', $createdon);
    } else {
        $date = date('r', strtotime($createdon));
    }

    // description из introtext или первые 200 символов контента
    $introtext = trim($res->get('introtext'));
    if (empty($introtext)) {
        $introtext = mb_substr($plainText, 0, 200, 'UTF-8');
    }
    $description = htmlspecialchars($introtext, ENT_XML1, 'UTF-8');

    // enclosure — обложка из miniShop2 product image
    $enclosure = '';
    // Пробуем получить оригинал изображения msProduct
    if ($res->get('class_key') === 'msProduct' || $res->get('class_key') === 'modDocument') {
        // Проверяем наличие изображения через miniShop2
        $productImage = '';
        // Способ 1: через TV или поле image
        $thumb = $res->get('image');
        if (empty($thumb)) {
            $thumb = $res->getTVValue('image');
        }
        // Способ 2: через таблицу msProductFile
        if (empty($thumb)) {
            $file = $modx->getObject('msProductFile', array(
                'product_id' => $resourceId,
                'parent'     => 0,
                'type'       => 'image',
            ));
            if ($file) {
                $thumb = $file->get('url');
            }
        }
        if (!empty($thumb)) {
            // Формируем полный URL
            if (strpos($thumb, 'http') !== 0) {
                $thumb = $siteUrl . '/' . ltrim($thumb, '/');
            }
            $enclosure = '<enclosure url="' . htmlspecialchars($thumb, ENT_XML1, 'UTF-8') . '" type="image/jpeg"/>';
        }
    }

    // --- Собираем item ---
    $output .= '<item>' . "\n";
    $output .= '  <title>' . $title . '</title>' . "\n";
    $output .= '  <link>' . $link . '</link>' . "\n";
    $output .= '  <guid>' . $link . '</guid>' . "\n";
    $output .= '  <pubDate>' . $date . '</pubDate>' . "\n";
    $output .= '  <category>format-article</category>' . "\n";
    $output .= '  <description><![CDATA[' . $introtext . ']]></description>' . "\n";
    if (!empty($enclosure)) {
        $output .= '  ' . $enclosure . "\n";
    }
    $output .= '  <content:encoded><![CDATA[' . $content . ']]></content:encoded>' . "\n";
    $output .= '</item>' . "\n";

    $itemCount++;
    unset($content, $plainText);
}

return $output;
