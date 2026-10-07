<?php
require_once(__DIR__.'/../../../../config.php');
$cmid = required_param('cmid', PARAM_INT);
$cm = get_coursemodule_from_id('quiz', $cmid, 0, false, MUST_EXIST);
require_login($cm->course, false, $cm);
require_sesskey();
$context = context_module::instance($cmid);
require_capability('mod/quiz:attempt', $context);
$key = (string)get_config('quizaccess_sergek','sharedkey');
if (strlen($key)<32) { throw new moodle_exception('notconfigured','quizaccess_sergek'); }
$state = \quizaccess_sergek\launch::state((int)$cm->instance, true);
$mode=(string)get_config('quizaccess_sergek','minimum_mode');
if (!in_array($mode,['strict','monitor'],true)) { $mode='strict'; }
$payload = ['exp'=>time()+1800, 'nonce'=>$state['nonce'], 'userid'=>(string)$USER->id, 'mode'=>$mode,
 'student_name'=>fullname($USER), 'exam_name'=>$cm->name,
 'quizid'=>(string)$cm->instance, 'url'=>(new moodle_url('/mod/quiz/view.php',['id'=>$cmid]))->out(false)];
$token = \quizaccess_sergek\launch::sign($payload,$key);
$PAGE->set_url(new moodle_url('/mod/quiz/accessrule/sergek/launch.php',['cmid'=>$cmid]));
$PAGE->set_context($context);$PAGE->set_title(get_string('pluginname','quizaccess_sergek'));
echo $OUTPUT->header();
// Only generated fixed-scheme URL. No arbitrary redirect or supplied URL parameter.
echo html_writer::tag('p',get_string('needactive','quizaccess_sergek'));
echo html_writer::tag('a',get_string('launch','quizaccess_sergek'),['href'=>'sergek://launch?token='.rawurlencode($token),'class'=>'btn btn-primary']);
echo $OUTPUT->footer();
