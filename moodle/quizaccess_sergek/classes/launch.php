<?php
namespace quizaccess_sergek;
defined('MOODLE_INTERNAL') || die();
final class launch {
    public static function canonical($value): string {
        if (is_array($value)) { ksort($value); }
        return json_encode($value, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    }
    public static function sign(array $payload, string $key): string {
        $raw = rtrim(strtr(base64_encode(self::canonical($payload)), '+/', '-_'), '=');
        return $raw . '.' . hash_hmac('sha256', $raw, $key);
    }
    public static function state(int $quizid, bool $renew = false): array {
        global $USER, $DB;
        $record = $DB->get_record('quizaccess_sergek_launch', ['userid'=>$USER->id, 'quizid'=>$quizid]);
        if (!$record && !$renew) { return []; }
        if ($renew) {
            $values = (object)['userid'=>$USER->id, 'quizid'=>$quizid, 'nonce'=>bin2hex(random_bytes(24)), 'created'=>time(), 'attemptid'=>0];
            $unfinished=$DB->get_records('quiz_attempts',['userid'=>$USER->id,'quiz'=>$quizid,'state'=>'inprogress','preview'=>0],'id DESC','id',0,1);
            if ($unfinished) { $values->attemptid=(int)reset($unfinished)->id; }
            if ($record) { $values->id=$record->id; $DB->update_record('quizaccess_sergek_launch', $values); }
            else { $DB->insert_record('quizaccess_sergek_launch', $values); }
            $record = $values;
        }
        return ['nonce'=>$record->nonce, 'created'=>(int)$record->created];
    }
    public static function status(int $quizid): array {
        $url = rtrim((string)get_config('quizaccess_sergek', 'huburl'), '/');
        $key = (string)get_config('quizaccess_sergek', 'sharedkey');
        if (strpos($url, 'https://') !== 0 || strlen($key) < 32) { return []; }
        $state = self::state($quizid);
        if (!$state) { return []; }
        static $cache=[];
        if (isset($cache[$state['nonce']])) { return $cache[$state['nonce']]; }
        $curl = new \curl();
        $curl->setHeader(['X-Sergek-Moodle: '.$key]);
        $raw = $curl->get($url.'/api/moodle/status', ['nonce'=>$state['nonce']], ['CURLOPT_TIMEOUT'=>5, 'CURLOPT_SSL_VERIFYPEER'=>true]);
        if ($curl->get_errno()) { return []; }
        $response = json_decode($raw, true);
        $mode=(string)get_config('quizaccess_sergek','minimum_mode');
        if (!in_array($mode,['strict','monitor'],true)) { $mode='strict'; }
        if (!is_array($response) || ($mode==='strict' && ($response['mode']??'')!=='strict')) { return []; }
        return $cache[$state['nonce']]=$response;
    }
    public static function active(int $quizid): bool {
        return !empty(self::status($quizid)['active']);
    }
    public static function prepared(int $quizid): bool {
        return !empty(self::status($quizid)['prepared']);
    }
}
