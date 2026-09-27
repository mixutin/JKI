import unittest
from engine import WakeGate, model_choice, speakable, Engine
from music import music_query

MODELS=['gpt-6-astra','gpt-6-sol','gpt-6-luna','gpt-5.6-sol','gpt-5.6-terra','gpt-5.5']


class VoiceTests(unittest.TestCase):
    def test_background_speech_is_ignored(self):
        gate=WakeGate()
        for text in ['open the terminal','tell jacob to go home','the jacket is blue','switch to sol']:
            self.assertIsNone(gate.accept(text,now=100))

    def test_whole_wake_name_and_command(self):
        self.assertEqual(WakeGate().accept('hey jake open the terminal',now=100),'open the terminal')
        self.assertEqual(WakeGate().accept('what time is it jake',now=100),'what time is it')

    def test_wake_without_command_allows_one_follow_up(self):
        gate=WakeGate()
        self.assertEqual(gate.accept('jake',now=100),'')
        self.assertEqual(gate.accept('what time is it',now=105),'what time is it')
        self.assertIsNone(gate.accept('delete a file',now=106))
        gate.accept('jake',now=200)
        self.assertIsNone(gate.accept('open a file',now=213))

    def test_low_confidence_wake_is_rejected(self):
        self.assertIsNone(WakeGate().accept('jake open files',words=[{'word':'jake','conf':.3}]))

    def test_model_switch_matches_real_catalog(self):
        self.assertEqual(model_choice('switch to soul',MODELS),'gpt-6-sol')
        self.assertEqual(model_choice('switch model to g p t five point six sol',MODELS),'gpt-5.6-sol')
        self.assertEqual(model_choice('use luna',MODELS),'gpt-6-luna')
        self.assertEqual(model_choice('switch to gpt five point five',MODELS),'gpt-5.5')
        self.assertEqual(model_choice('switch model to gpt seven',MODELS),'')
        self.assertEqual(model_choice('switch to gpt six terra',MODELS),'')
        self.assertIsNone(model_choice('tell me about the sol model',MODELS))
        self.assertIsNone(model_choice('change the wallpaper',MODELS))

    def test_spoken_reply_omits_code_and_link_destinations(self):
        text=speakable('**Done.** [report](/tmp/report.md)\n```bash\nrm file\n```')
        self.assertIn('Done.',text)
        self.assertNotIn('rm file',text)
        self.assertNotIn('/tmp',text)

    def test_repeated_completion_is_spoken_once(self):
        engine=Engine({'thread_id':'test'})
        item={'id':'answer-1','type':'agentMessage','phase':'final_answer','text':'Done.'}
        engine._event({'method':'item/completed','params':{'threadId':'test','turnId':'1','item':item}})
        engine._event({'method':'turn/completed','params':{'threadId':'test','turn':{'id':'1','status':'completed'}}})
        self.assertEqual(engine.speech.get_nowait(),'Done.')
        self.assertTrue(engine.speech.empty())

    def test_other_thread_responses_are_ignored(self):
        engine=Engine({'thread_id':'test'})
        engine._event({'method':'item/completed','params':{'threadId':'other','item':{
            'id':'1','type':'agentMessage','phase':'final_answer','text':'Unrelated'}}})
        self.assertTrue(engine.speech.empty())

    def test_music_request_respects_named_app(self):
        self.assertEqual(music_query('play the song take on me by a ha'),'take on me by a ha')
        self.assertIsNone(music_query('play take on me on spotify'))
        self.assertIsNone(music_query('play a chess game'))


if __name__=='__main__':unittest.main()
