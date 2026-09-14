import unittest

from wecom_kf.history import visible_content, REDACTED


class HistoryTests(unittest.TestCase):
    def test_password_phase_and_known_credentials_are_hidden(self):
        self.assertEqual(visible_content({'msgtype':'text','text':{'content':'unlabeled-password'}}, password_entry=True)[1:3], (REDACTED, True))
        for value in ['我的已绑定密码 secret-value', 'password: secret-value', 'Authorization: Bearer secret-value']:
            result = visible_content({'msgtype':'text','text':{'content':value}}, known_secrets=['secret-value'])
            self.assertNotIn('secret-value', result[1])
            self.assertTrue(result[2])

    def test_menu_keeps_visible_copy_without_actions_or_api_secrets(self):
        message = {'msgtype':'msgmenu','code':'PRIVATE-CODE','msgmenu':{'head_content':'选择业务','tail_content':'请点击', 'list':[
            {'type':'click','click':{'id':'PRIVATE-ACTION','content':'头歌'}}, {'type':'text','text':{'content':'说明'}},
        ]}}
        self.assertEqual(visible_content(message), ('msgmenu','选择业务\n头歌\n说明\n请点击',False,False))

    def test_nontext_and_overlong_content_are_explicit(self):
        self.assertEqual(visible_content({'msgtype':'image','image':{'media_id':'PRIVATE-MEDIA'}})[1], '[image]')
        result = visible_content({'msgtype':'text','text':{'content':'字'*30000}})
        self.assertTrue(result[3])
        self.assertLessEqual(len(result[1].encode()),60000)
