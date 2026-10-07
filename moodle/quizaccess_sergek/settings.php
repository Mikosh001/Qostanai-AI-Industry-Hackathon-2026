<?php
defined('MOODLE_INTERNAL') || die();
if ($ADMIN->fulltree) {
    $settings->add(new admin_setting_configtext('quizaccess_sergek/huburl', get_string('huburl','quizaccess_sergek'), get_string('huburl_desc','quizaccess_sergek'), '', PARAM_URL));
    $settings->add(new admin_setting_configpasswordunmask('quizaccess_sergek/sharedkey', get_string('sharedkey','quizaccess_sergek'), get_string('sharedkey_desc','quizaccess_sergek'), ''));
    $settings->add(new admin_setting_configselect('quizaccess_sergek/minimum_mode',get_string('minimum_mode','quizaccess_sergek'),get_string('minimum_mode_desc','quizaccess_sergek'),'strict',['strict'=>'Strict','monitor'=>'Monitor (software test only)']));
}
