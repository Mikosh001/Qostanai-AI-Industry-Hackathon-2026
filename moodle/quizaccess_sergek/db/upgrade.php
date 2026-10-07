<?php
defined('MOODLE_INTERNAL') || die();
function xmldb_quizaccess_sergek_upgrade($oldversion) {
    global $DB;
    $manager=$DB->get_manager();
    if ($oldversion<2026100701) {
        $table=new xmldb_table('quizaccess_sergek_launch');
        $field=new xmldb_field('attemptid',XMLDB_TYPE_INTEGER,'10',null,XMLDB_NOTNULL,null,'0','created');
        if (!$manager->field_exists($table,$field)) { $manager->add_field($table,$field); }
        $index=new xmldb_index('nonce',XMLDB_INDEX_UNIQUE,['nonce']);
        if (!$manager->index_exists($table,$index)) { $manager->add_index($table,$index); }
        upgrade_plugin_savepoint(true,2026100701,'quizaccess','sergek');
    }
    return true;
}
