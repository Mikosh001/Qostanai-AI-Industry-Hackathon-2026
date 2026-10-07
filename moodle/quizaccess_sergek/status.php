<?php
define('NO_MOODLE_COOKIES',true);
require_once(__DIR__.'/../../../../config.php');
header('Content-Type: application/json');
$key=(string)get_config('quizaccess_sergek','sharedkey');
if (strlen($key)<32 || !hash_equals($key,$_SERVER['HTTP_X_SERGEK_MOODLE']??'')) { http_response_code(403); echo '{}'; exit; }
$nonce=required_param('nonce',PARAM_ALPHANUM);
$record=$DB->get_record('quizaccess_sergek_launch',['nonce'=>$nonce]);
if (!$record) { http_response_code(404); echo '{}'; exit; }
$attempt=$record->attemptid ? $DB->get_record('quiz_attempts',['id'=>$record->attemptid,'userid'=>$record->userid,'quiz'=>$record->quizid]) : false;
echo json_encode(['nonce'=>$nonce,'userid'=>(string)$record->userid,'quizid'=>(string)$record->quizid,
    'attemptid'=>$attempt ? (string)$attempt->id : '', 'state'=>$attempt ? $attempt->state : 'not_started',
    'started'=>$attempt ? $attempt->timestart : null,'ended'=>$attempt && $attempt->state==='finished' ? $attempt->timefinish : null]);
