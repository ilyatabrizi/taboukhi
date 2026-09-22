<?php
/*
 * TABOUKHI — application receiver.   https://taboukhi.com/api/apply.php
 *
 * Takes the multipart POST sent by js/adapter.js (endpoint mode), checks it again on the
 * server, stores it OUTSIDE every web root, and emails it — CV attached — to NOTIFY_TO.
 *
 *   200 {ok:true, reference}        stored and mailed (suspected spam: flagged in the subject, filed under quarantine/)
 *   422 {ok:false, fieldErrors}     keys match the form: full_name email phone discipline portfolio_url consent cv
 *   413 too large · 429 too many (Retry-After) · 403 wrong origin · 405 not POST · 500 server
 *
 * No database and no secrets: mail leaves through the host's own mail server, as info@.
 * Written for PHP 7.4 and up (Limoo has defaulted new domains to 7.4 before).
 */
declare(strict_types=1);

const NOTIFY_TO  = 'info@taboukhi.com';
const MAIL_FROM  = 'info@taboukhi.com';
const MAIL_NAME  = 'TABOUKHI Applications';
const SITE_HOSTS = ['taboukhi.com', 'www.taboukhi.com'];
const MAX_FILE   = 10485760;      // 10 MB, as the form says
const MAX_BODY   = 13631488;      // 13 MB: the file, the fields and the multipart overhead
const PER_HOUR   = 3;             // submissions per connection
const PER_DAY    = 10;
const DUP_WINDOW = 600;           // the same email + discipline within 10 minutes is one application
const STORE_DIR  = '';            // '' = ~/taboukhi-applications, beside public_html, never inside it

const DISCIPLINES = [
    'design-studio'          => 'Design Studio',
    'atelier'                => 'Atelier',
    'precious-materials'     => 'Precious Materials',
    'development-production' => 'Development & Production',
    'optics-fit'             => 'Optics & Fit',
    'private-clients'        => 'Private Clients & Bespoke',
    'image-communications'   => 'Image & Communications',
    'house-operations'       => 'House Operations',
    'open'                   => 'Open application',
];

ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
header('X-Robots-Tag: noindex');

function reply(int $code, array $body, array $headers = []): void
{
    http_response_code($code);
    foreach ($headers as $h) {
        header($h);
    }
    echo json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
    exit;
}

if (PHP_VERSION_ID < 70400) {
    reply(500, ['ok' => false, 'error' => 'php_version', 'need' => '7.4+', 'have' => PHP_VERSION]);
}

function cut(string $s, int $max): string
{
    return function_exists('mb_substr') ? mb_substr($s, 0, $max, 'UTF-8') : substr($s, 0, $max);
}

function len(string $s): int
{
    return function_exists('mb_strlen') ? mb_strlen($s, 'UTF-8') : strlen($s);
}

function field(string $key, int $max): string
{
    $v = isset($_POST[$key]) && is_string($_POST[$key]) ? $_POST[$key] : '';
    $v = trim(str_replace("\0", '', $v));
    return cut($v, $max);
}

/** One line of text: no line breaks, no quotes — safe inside a mail header. */
function one_line(string $s): string
{
    return trim(preg_replace('/[\r\n"]+/', ' ', $s) ?? '');
}

function store_dir(): string
{
    if (STORE_DIR !== '') {
        return rtrim(STORE_DIR, '/');
    }
    $doc = (string) realpath((string) ($_SERVER['DOCUMENT_ROOT'] ?? ''));
    if (preg_match('#^(/home[0-9]*/[^/]+)(?:/|$)#', $doc, $m)) {
        return $m[1] . '/taboukhi-applications';          // the cPanel home: above every document root
    }
    $home = getenv('HOME');
    if (is_string($home) && $home !== '' && is_dir($home)) {
        return rtrim($home, '/') . '/taboukhi-applications';
    }
    return dirname(__DIR__, 2) . '/taboukhi-applications';
}

function ensure_dirs(string $root): void
{
    foreach (['', '/applications', '/quarantine', '/files', '/rate'] as $sub) {
        $d = $root . $sub;
        if (!is_dir($d) && !@mkdir($d, 0700, true) && !is_dir($d)) {
            throw new RuntimeException('cannot create ' . $d);
        }
    }
    // Belt and braces, should the folder ever end up under a web root.
    if (!is_file($root . '/.htaccess')) {
        @file_put_contents($root . '/.htaccess', "Require all denied\n<IfModule !mod_authz_core.c>\n  Deny from all\n</IfModule>\n");
    }
}

/** Read-modify-write a small JSON file under an exclusive lock. */
function with_json(string $path, callable $fn)
{
    $h = fopen($path, 'c+');
    if ($h === false) {
        throw new RuntimeException('cannot open ' . $path);
    }
    flock($h, LOCK_EX);
    $raw = stream_get_contents($h);
    $data = json_decode($raw === false || $raw === '' ? '[]' : $raw, true);
    if (!is_array($data)) {
        $data = [];
    }
    $result = $fn($data);
    ftruncate($h, 0);
    rewind($h);
    fwrite($h, json_encode($data));
    fflush($h);
    flock($h, LOCK_UN);
    fclose($h);
    @chmod($path, 0600);
    return $result;
}

function log_line(string $root, string $what): void
{
    @file_put_contents($root . '/errors.log', gmdate('c') . ' ' . $what . "\n", FILE_APPEND | LOCK_EX);
}

function mime_word(string $s): string
{
    return '=?UTF-8?B?' . base64_encode(one_line($s)) . '?=';
}

function send_mail(array $app, ?array $file, string $flag = ''): bool
{
    $b = 'tbk_' . bin2hex(random_bytes(12));
    $subject = $flag . 'Application — ' . $app['discipline_name'] . ' — ' . $app['full_name'] . ' (' . $app['reference'] . ')';
    $lines = [
        'New application for TABOUKHI.',
        '',
        'Reference:   ' . $app['reference'],
        'Received:    ' . $app['received_at_text'],
        '',
        'Name:        ' . $app['full_name'],
        'Email:       ' . $app['email'],
        'Phone:       ' . ($app['phone'] !== '' ? $app['phone'] : '—'),
        'Based in:    ' . ($app['location'] !== '' ? $app['location'] : '—'),
        'Discipline:  ' . $app['discipline_name'],
        'Position:    ' . ($app['current_role'] !== '' ? $app['current_role'] : '—'),
        'Link:        ' . ($app['portfolio_url'] !== '' ? $app['portfolio_url'] : '—'),
        'File:        ' . ($file ? $file['name'] . ' (' . round($file['size'] / 1024) . ' KB, attached)' : '—'),
        '',
        'Note:',
        $app['message'] !== '' ? $app['message'] : '—',
        '',
        'Consent given (wording version ' . $app['consent_version'] . ').',
        $flag !== '' ? 'Flagged as possible spam (hidden field filled, sent within seconds, or links/markup in the note). Check before replying.' : '',
        'Reply to this email to write to the applicant.',
    ];
    $text = implode("\r\n", $lines);
    $headers = [
        'From: ' . mime_word(MAIL_NAME) . ' <' . MAIL_FROM . '>',
        'Reply-To: ' . mime_word($app['full_name']) . ' <' . $app['email'] . '>',
        'MIME-Version: 1.0',
        'Content-Type: multipart/mixed; boundary="' . $b . '"',
    ];
    $body = "--$b\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: base64\r\n\r\n"
          . chunk_split(base64_encode($text)) . "\r\n";
    if ($file) {
        $bytes = file_get_contents($file['path']);
        if ($bytes !== false) {
            $name = preg_replace('/[^A-Za-z0-9._-]+/', '-', $file['name']) ?: ('cv.' . $file['ext']);
            $body .= "--$b\r\nContent-Type: " . $file['type'] . "; name=\"$name\"\r\n"
                   . "Content-Transfer-Encoding: base64\r\nContent-Disposition: attachment; filename=\"$name\"\r\n\r\n"
                   . chunk_split(base64_encode($bytes)) . "\r\n";
        }
    }
    $body .= "--$b--\r\n";
    $sent = @mail(NOTIFY_TO, mime_word($subject), $body, implode("\r\n", $headers), '-f' . MAIL_FROM);
    if (!$sent) {
        $sent = @mail(NOTIFY_TO, mime_word($subject), $body, implode("\r\n", $headers));   // some hosts refuse -f
    }
    return $sent;
}

$root = store_dir();
try {
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
        reply(405, ['ok' => false, 'error' => 'method_not_allowed'], ['Allow: POST']);
    }
    $origin = (string) ($_SERVER['HTTP_ORIGIN'] ?? '');
    if ($origin !== '' && !in_array(strtolower((string) parse_url($origin, PHP_URL_HOST)), SITE_HOSTS, true)) {
        reply(403, ['ok' => false, 'error' => 'origin']);
    }
    $length = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
    if ($length > MAX_BODY || ($length > 0 && empty($_POST) && empty($_FILES))) {
        reply(413, ['ok' => false, 'error' => 'too_large']);        // over our cap, or over post_max_size
    }
    ensure_dirs($root);
    $now = time();

    // ── Rate: counted per connection, kept as a hash, never the address itself.
    $who = hash('sha256', (string) ($_SERVER['REMOTE_ADDR'] ?? '') . '|' . __FILE__);
    $retry = with_json($root . '/rate/' . substr($who, 0, 32) . '.json', function (array &$times) use ($now) {
        $times = array_values(array_filter($times, function ($t) use ($now) { return is_int($t) && $t > $now - 86400; }));
        $hour = array_filter($times, function ($t) use ($now) { return $t > $now - 3600; });
        if (count($hour) >= PER_HOUR) {
            return 3600 - ($now - min($hour));
        }
        if (count($times) >= PER_DAY) {
            return 86400 - ($now - min($times));
        }
        $times[] = $now;
        return 0;
    });
    if ($retry > 0) {
        reply(429, ['ok' => false, 'error' => 'rate_limited'], ['Retry-After: ' . max(60, (int) $retry)]);
    }

    // ── Fields, checked again: the browser's checks are a courtesy, these are the rule.
    $app = [
        'full_name'       => field('full_name', 80),
        'email'           => field('email', 254),
        'phone'           => field('phone', 24),
        'location'        => field('location', 100),
        'discipline'      => field('discipline', 40),
        'current_role'    => field('current_role', 120),
        'portfolio_url'   => field('portfolio_url', 300),
        'message'         => field('message', 1500),
        'consent_version' => one_line(field('consent_version', 40)),
    ];
    $errors = [];
    if (len($app['full_name']) < 2 || !preg_match('/\p{L}/u', $app['full_name'])) {
        $errors['full_name'] = 'Please enter your name.';
    }
    if (!filter_var($app['email'], FILTER_VALIDATE_EMAIL) || preg_match('/[\r\n]/', $app['email'])) {
        $errors['email'] = 'That email address does not look complete.';
    }
    if ($app['phone'] !== '' && (!preg_match('/^[\d\s+().-]{7,24}$/', $app['phone']) || preg_match_all('/\d/', $app['phone']) < 7)) {
        $errors['phone'] = 'Please check this number, or leave it empty.';
    }
    if (!array_key_exists($app['discipline'], DISCIPLINES)) {
        $errors['discipline'] = 'Please choose the discipline closest to your work.';
    }
    if ($app['portfolio_url'] !== '') {
        $u = parse_url($app['portfolio_url']);
        $ok = filter_var($app['portfolio_url'], FILTER_VALIDATE_URL)
            && isset($u['scheme'], $u['host']) && in_array(strtolower($u['scheme']), ['http', 'https'], true)
            && strpos($u['host'], '.') !== false;
        if (!$ok) {
            $errors['portfolio_url'] = 'This link does not look complete. Paste the full address, such as https://yourname.com';
        }
    }
    if (field('consent', 8) !== 'true') {
        $errors['consent'] = 'Please agree, so that we may keep your application to consider it.';
    }

    // ── The file: size, kind, and the bytes themselves.
    $file = null;
    $up = $_FILES['cv'] ?? null;
    if (is_array($up) && ($up['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_NO_FILE) {
        if (in_array($up['error'], [UPLOAD_ERR_INI_SIZE, UPLOAD_ERR_FORM_SIZE], true) || (int) $up['size'] > MAX_FILE) {
            reply(413, ['ok' => false, 'error' => 'too_large']);
        }
        if ($up['error'] !== UPLOAD_ERR_OK || !is_uploaded_file($up['tmp_name'])) {
            $errors['cv'] = 'This file could not be received. Please try again, or share a link instead.';
        } else {
            $ext = strtolower(pathinfo((string) $up['name'], PATHINFO_EXTENSION));
            $head = (string) file_get_contents($up['tmp_name'], false, null, 0, 1024);
            $kinds = [
                'pdf'  => ['application/pdf', strpos($head, '%PDF-') !== false],
                'doc'  => ['application/msword', strncmp($head, "\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1", 8) === 0],
                'docx' => ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', strncmp($head, "PK\x03\x04", 4) === 0],
            ];
            if (!isset($kinds[$ext]) || !$kinds[$ext][1] || (int) $up['size'] === 0) {
                $errors['cv'] = 'Please choose a PDF or a Word document.';
            } else {
                $file = ['tmp' => $up['tmp_name'], 'name' => cut(basename((string) $up['name']), 120),
                         'size' => (int) $up['size'], 'ext' => $ext, 'type' => $kinds[$ext][0]];
            }
        }
    }
    if (!$file && $app['portfolio_url'] === '' && !isset($errors['portfolio_url']) && !isset($errors['cv'])) {
        $errors['portfolio_url'] = 'Add a link or attach a file, so we can see your work.';
    }
    if ($errors) {
        reply(422, ['ok' => false, 'error' => 'invalid', 'fieldErrors' => $errors]);
    }

    // ── One application, not two: an impatient second press gets the first reference.
    // Registered only after the application is safely stored, so a failed attempt is retried
    // for real instead of being answered with the reference of something never saved.
    $dupKey = hash('sha256', strtolower($app['email']) . '|' . $app['discipline']);
    $first = with_json($root . '/recent.json', function (array &$recent) use ($dupKey, $now) {
        foreach ($recent as $k => $v) {
            if (!is_array($v) || ($v[1] ?? 0) < $now - DUP_WINDOW) {
                unset($recent[$k]);
            }
        }
        return isset($recent[$dupKey]) ? $recent[$dupKey][0] : null;
    });
    if (is_string($first)) {
        reply(200, ['ok' => true, 'reference' => $first]);
    }
    $reference = 'TBK-' . strtoupper(bin2hex(random_bytes(3)));

    // ── Quarantine rather than refuse: a bot learns nothing, and nothing real is lost.
    $meta = json_decode(field('meta', 400), true);
    $meta = is_array($meta) ? $meta : [];
    $links = preg_match_all('#https?://#i', $app['message']);
    $quarantined = !empty($meta['hp']) || (int) ($meta['elapsed_ms'] ?? 0) < 4000
        || $links > 2 || preg_match('/<\s*[a-z!\/]/i', $app['message']);

    $stamp = gmdate('Ymd-His', $now);
    if ($file) {
        $safe = preg_replace('/[^A-Za-z0-9._-]+/', '-', pathinfo($file['name'], PATHINFO_FILENAME)) ?: 'cv';
        $dest = $root . '/files/' . $stamp . '-' . $reference . '-' . cut($safe, 60) . '.' . $file['ext'];
        if (!move_uploaded_file($file['tmp'], $dest)) {
            throw new RuntimeException('cannot store the upload');
        }
        @chmod($dest, 0600);
        $file['path'] = $dest;
    }
    $app['reference'] = $reference;
    $app['discipline_name'] = DISCIPLINES[$app['discipline']];
    $app['received_at'] = gmdate('c', $now);
    $app['received_at_text'] = gmdate('j M Y, H:i', $now) . ' UTC';
    $record = $app + [
        'file' => $file ? ['name' => $file['name'], 'stored_as' => basename($file['path']), 'size' => $file['size'], 'type' => $file['type']] : null,
        'consent' => true,
        'meta' => ['elapsed_ms' => (int) ($meta['elapsed_ms'] ?? 0), 'hp' => !empty($meta['hp'])],
        'client' => ['who' => substr($who, 0, 16), 'user_agent' => cut((string) ($_SERVER['HTTP_USER_AGENT'] ?? ''), 300)],
        'quarantined' => (bool) $quarantined,
        'mailed' => false,
    ];
    $recordPath = $root . ($quarantined ? '/quarantine/' : '/applications/') . $stamp . '-' . $reference . '.json';
    if (file_put_contents($recordPath, json_encode($record, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE), LOCK_EX) === false) {
        throw new RuntimeException('cannot store the application');
    }
    @chmod($recordPath, 0600);
    with_json($root . '/recent.json', function (array &$recent) use ($dupKey, $now, $reference) {
        $recent[$dupKey] = [$reference, $now];
        return null;
    });

    // Everything is mailed — a real candidate misjudged as a bot must still be seen. Suspects
    // are flagged in the subject so they can be filtered, and filed under quarantine/.
    if (send_mail($app, $file, $quarantined ? '[Possible spam] ' : '')) {
        $record['mailed'] = true;
        @file_put_contents($recordPath, json_encode($record, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE), LOCK_EX);
    } else {
        log_line($root, 'mail() failed for ' . $reference . ' — the application is stored at ' . basename($recordPath));
    }
    reply(200, ['ok' => true, 'reference' => $reference]);
} catch (Throwable $e) {
    log_line($root, get_class($e) . ': ' . $e->getMessage() . ' @' . $e->getLine());
    reply(500, ['ok' => false, 'error' => 'server']);
}
