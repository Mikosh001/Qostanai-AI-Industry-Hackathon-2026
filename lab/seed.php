<?php
// Creates synthetic acceptance data ONLY in the explicitly selected isolated lab.
define('CLI_SCRIPT', true);
$lab = getenv('SERGEK_LAB');
if (!$lab || !is_file($lab.'/lab.json')) { throw new Exception('Explicit Sergek lab required'); }
$meta=json_decode(file_get_contents($lab.'/lab.json'),true);
$credentials=json_decode(file_get_contents($lab.'/credentials.json'),true);
require($meta['moodle'].'/config.php');
if ($CFG->wwwroot !== 'https://localhost' || strpos($CFG->dataroot, $lab) !== 0) { throw new Exception('Refusing to seed a university site'); }
require_once($CFG->libdir.'/testing/generator/lib.php');
require_once($CFG->dirroot.'/mod/quiz/locallib.php');
\core\session\manager::set_user(get_admin());
$generator=new testing_data_generator();
$student=$DB->get_record('user',['username'=>$credentials['student']]);
if (!$student) { $student=$generator->create_user(['username'=>$credentials['student'],'password'=>$credentials['studentpass'],'firstname'=>'Acceptance','lastname'=>'Student','email'=>'student@localhost.invalid']); }
update_internal_user_password($student, $credentials['studentpass']);
$course=$DB->get_record('course',['shortname'=>'SERGEK-LAB']);
if (!$course) { $course=$generator->create_course(['shortname'=>'SERGEK-LAB','fullname'=>'Sergek integration acceptance','format'=>'topics']); }
$DB->set_field('course','fullname','Sergек — таныстыру курсы',['id'=>$course->id]);
$generator->enrol_user($student->id,$course->id,'student');
if (!empty($credentials['moodle_teacher']) && !empty($credentials['moodle_teacher_password'])) {
    $teacher=$DB->get_record('user',['username'=>$credentials['moodle_teacher']]);
    if (!$teacher) {$teacher=$generator->create_user(['username'=>$credentials['moodle_teacher'],'password'=>$credentials['moodle_teacher_password'],'firstname'=>'Sergek','lastname'=>'Teacher','email'=>'teacher@localhost.invalid']);}
    update_internal_user_password($teacher, $credentials['moodle_teacher_password']);
    $generator->enrol_user($teacher->id,$course->id,'editingteacher');
}
$quiz=$DB->get_record('quiz',['course'=>$course->id,'name'=>'Sergek protected acceptance quiz']);
if (!$quiz) { $quiz=$DB->get_record('quiz',['course'=>$course->id,'name'=>'Sergек — қорғалған таныстыру тесті']); }
if (!$quiz) {
    $quiz=$generator->create_module('quiz',['course'=>$course->id,'name'=>'Sergek protected acceptance quiz','timelimit'=>1800,'attempts'=>0,'sergekrequired'=>1,'preferredbehaviour'=>'deferredfeedback']);
}
$DB->set_field('quiz','name','Sergек — қорғалған таныстыру тесті',['id'=>$quiz->id]);
if (!$DB->record_exists('quiz_slots',['quizid'=>$quiz->id])) {
    $qgen=$generator->get_plugin_generator('core_question');
    $category=$qgen->create_question_category(['contextid'=>context_course::instance($course->id)->id]);
    $editor=['text'=>'','format'=>FORMAT_HTML];
    $form=(object)['category'=>(string)$category->id,'name'=>'Sergek local inference','questiontext'=>['text'=>'Sergek performs camera inference on the local computer.','format'=>FORMAT_HTML],'generalfeedback'=>$editor,'feedbacktrue'=>$editor,'feedbackfalse'=>$editor,'correctanswer'=>1,'defaultmark'=>1,'penalty'=>1];
    $q=question_bank::get_qtype('truefalse')->save_question((object)['qtype'=>'truefalse'],$form);
    quiz_add_quiz_question($q->id,$quiz);
    quiz_update_sumgrades($quiz);
}
$DB->set_field('quizaccess_sergek','enabled',1,['quizid'=>$quiz->id]);
set_config('huburl','https://localhost:9443','quizaccess_sergek');
set_config('sharedkey',$credentials['sharedkey'],'quizaccess_sergek');
// Software integration acceptance deliberately does not switch OS restrictions on this PC.
set_config('minimum_mode',getenv('SERGEK_LAB_MODE') === 'strict' ? 'strict' : 'monitor','quizaccess_sergek');
set_config('auth','manual');set_config('enablecompletion',0);
$cm=get_coursemodule_from_instance('quiz',$quiz->id,$course->id,false,MUST_EXIST);
file_put_contents($lab.'/exam.json',json_encode(['studentid'=>$student->id,'courseid'=>$course->id,'quizid'=>$quiz->id,'cmid'=>$cm->id,'url'=>'https://localhost/mod/quiz/view.php?id='.$cm->id]));
echo "Synthetic course, student and protected quiz ready.\n";
