<?php
defined('MOODLE_INTERNAL') || die();
$observers = [
    ['eventname' => '\\mod_quiz\\event\\attempt_started',
     'callback' => '\\quizaccess_sergek\\observer::started'],
    ['eventname' => '\\mod_quiz\\event\\attempt_submitted',
     'callback' => '\\quizaccess_sergek\\observer::submitted'],
];
