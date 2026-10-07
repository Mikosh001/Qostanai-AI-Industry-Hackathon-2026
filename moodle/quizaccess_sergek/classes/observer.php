<?php
namespace quizaccess_sergek;
defined('MOODLE_INTERNAL') || die();
final class observer {
    public static function started(\mod_quiz\event\attempt_started $event): void {
        global $DB;
        $attempt=$DB->get_record('quiz_attempts',['id'=>$event->objectid]);
        if (!$attempt) { return; }
        $launch=$DB->get_record('quizaccess_sergek_launch',['userid'=>$attempt->userid,'quizid'=>$attempt->quiz]);
        if ($launch) { $launch->attemptid=$attempt->id; $DB->update_record('quizaccess_sergek_launch',$launch); }
    }
    public static function submitted(\mod_quiz\event\attempt_submitted $event): void {
        global $DB;
        $attempt=$DB->get_record('quiz_attempts', ['id'=>$event->objectid]);
        if (!$attempt || $attempt->state!=='finished') { return; }
        $state=$DB->get_record('quizaccess_sergek_launch', ['userid'=>$attempt->userid, 'quizid'=>$attempt->quiz]);
        if (!$state || (int)$state->attemptid !== (int)$attempt->id) { return; }
        $url=rtrim((string)get_config('quizaccess_sergek','huburl'),'/');
        $key=(string)get_config('quizaccess_sergek','sharedkey');
        if (strpos($url,'https://')!==0 || strlen($key)<32) { return; }
        $curl=new \curl();
        $curl->setHeader(['X-Sergek-Moodle: '.$key, 'Content-Type: application/json']);
        $curl->post($url.'/api/moodle/finish', json_encode([
            'nonce'=>$state->nonce, 'userid'=>(string)$attempt->userid,
            'quizid'=>(string)$attempt->quiz, 'attemptid'=>(string)$attempt->id,
        ]), ['CURLOPT_TIMEOUT'=>5, 'CURLOPT_SSL_VERIFYPEER'=>true]);
        // If notification fails, the agent polls status.php for this exact bound attempt.
    }
}
