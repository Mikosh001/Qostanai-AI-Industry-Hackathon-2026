<?php
defined('MOODLE_INTERNAL') || die();
require_once($CFG->dirroot.'/mod/quiz/accessrule/accessrulebase.php');

class quizaccess_sergek extends \mod_quiz\local\access_rule_base {
    public static function make(\mod_quiz\quiz_settings $quizobj, $timenow, $canignoretimelimits) {
        global $DB;
        if (!$DB->get_field('quizaccess_sergek','enabled',['quizid'=>$quizobj->get_quizid()])) { return null; }
        return new self($quizobj,$timenow);
    }
    public function description() {
        if (\quizaccess_sergek\launch::active((int)$this->quiz->id)) {
            return get_string('ready','quizaccess_sergek');
        }
        if (\quizaccess_sergek\launch::prepared((int)$this->quiz->id)) {
            return get_string('prepared','quizaccess_sergek');
        }
        $url = new moodle_url('/mod/quiz/accessrule/sergek/launch.php',['cmid'=>$this->quizobj->get_cmid(),'sesskey'=>sesskey()]);
        return get_string('description','quizaccess_sergek').' '.html_writer::link($url,get_string('launch','quizaccess_sergek'));
    }
    public function prevent_new_attempt($numprevattempts, $lastattempt) {
        return (\quizaccess_sergek\launch::active((int)$this->quiz->id) || \quizaccess_sergek\launch::prepared((int)$this->quiz->id)) ? false : get_string('needactive','quizaccess_sergek');
    }
    public function is_preflight_check_required($attemptid) {
        global $SESSION;
        $state=\quizaccess_sergek\launch::state((int)$this->quiz->id);
        return empty($state['nonce']) || ($SESSION->sergekpassed[$this->quiz->id]??'') !== $state['nonce'];
    }
    public function notify_preflight_check_passed($attemptid) {
        global $SESSION;
        $state=\quizaccess_sergek\launch::state((int)$this->quiz->id);
        if (!isset($SESSION->sergekpassed)) { $SESSION->sergekpassed=[]; }
        $SESSION->sergekpassed[$this->quiz->id]=$state['nonce']??'';
    }
    public function current_attempt_finished() { global $SESSION; unset($SESSION->sergekpassed[$this->quiz->id]); }
    public function prevent_access() {
        global $PAGE, $USER, $DB;
        $path=$PAGE->url->get_path();
        if (substr($path,-9)==='/view.php' && \quizaccess_sergek\launch::prepared((int)$this->quiz->id)) { return false; }
        // Finished answers remain viewable even after the submission callback releases protection.
        if (substr($path,-11)==='/review.php') {
            $attemptid=optional_param('attempt',0,PARAM_INT);
            if ($DB->record_exists('quiz_attempts',['id'=>$attemptid,'userid'=>$USER->id,'quiz'=>$this->quiz->id,'state'=>'finished'])) { return false; }
        }
        return \quizaccess_sergek\launch::active((int)$this->quiz->id) ? false : get_string('needactive','quizaccess_sergek');
    }
    public function add_preflight_check_form_fields(\mod_quiz\form\preflight_check_form $quizform, MoodleQuickForm $mform, $attemptid) {
        $mform->addElement('static','sergeknotice','',get_string('description','quizaccess_sergek'));
    }
    public function validate_preflight_check($data,$files,$errors,$attemptid) {
        if (!\quizaccess_sergek\launch::active((int)$this->quiz->id)) {
            $errors['sergeknotice']=get_string('needactive','quizaccess_sergek');
        }
        return $errors;
    }
    public static function add_settings_form_fields(mod_quiz_mod_form $quizform,MoodleQuickForm $mform) {
        $mform->addElement('advcheckbox','sergekrequired',get_string('required','quizaccess_sergek'));
        $mform->addHelpButton('sergekrequired','required','quizaccess_sergek');
        $mform->setDefault('sergekrequired',0);
    }
    public static function save_settings($quiz) {
        global $DB;
        $record=$DB->get_record('quizaccess_sergek',['quizid'=>$quiz->id]);
        if ($record) {$record->enabled=!empty($quiz->sergekrequired)?1:0;$DB->update_record('quizaccess_sergek',$record);}
        else {$DB->insert_record('quizaccess_sergek',(object)['quizid'=>$quiz->id,'enabled'=>!empty($quiz->sergekrequired)?1:0]);}
    }
    public static function delete_settings($quiz) {global $DB;$DB->delete_records('quizaccess_sergek',['quizid'=>$quiz->id]);$DB->delete_records('quizaccess_sergek_launch',['quizid'=>$quiz->id]);}
    public static function get_settings_sql($quizid) {
        return ['sg.enabled AS sergekrequired','LEFT JOIN {quizaccess_sergek} sg ON sg.quizid = quiz.id',[]];
    }
}
