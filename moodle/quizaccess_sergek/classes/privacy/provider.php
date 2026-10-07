<?php
namespace quizaccess_sergek\privacy;
defined('MOODLE_INTERNAL') || die();
class provider implements \core_privacy\local\metadata\provider {
    public static function get_metadata(\core_privacy\local\metadata\collection $collection): \core_privacy\local\metadata\collection {
        return $collection->add_external_location_link('sergek', ['userid'=>'privacy:metadata','quizid'=>'privacy:metadata','nonce'=>'privacy:metadata'], 'privacy:metadata');
    }
}
