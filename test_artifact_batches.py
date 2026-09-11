import copy
import unittest
from artifact_batches import validate


def manifest():
    image={'repo':'rollingfruit/agent-governance-gw','source_sha':'a'*40,'image_id':'sha256:'+'b'*64}
    return {'schema_version':1,'build_id':'test-123','target':'ci-compose','suite_ids':['E01','E02','E03'],
            'baseline_enabled':True,'baseline_images':{'governance':image},
            'candidate_images':{'governance':{**image,'archive_name':'governance.tar','archive_sha256':'c'*64}}}


class ArtifactValidation(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(len(validate(manifest())),3)

    def test_invalid(self):
        for key,value in [('build_id','../escape'),('target','cce'),('suite_ids',[]),('suite_ids',['E04']),('suite_ids',['E01','E01']),('baseline_enabled','yes')]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                body=manifest();body[key]=value;validate(body)

    def test_exact_image_and_source(self):
        for key,value in [('image_id','latest'),('source_sha','abc'),('archive_name','../x.tar'),('archive_sha256','wrong'),('repo','rollingfruit/other')]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                body=copy.deepcopy(manifest());body['candidate_images']['governance'][key]=value;validate(body)

if __name__=='__main__':unittest.main()
