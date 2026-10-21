import json
import unittest

from pokemon_index.mercari_discovery import preload_product_urls


def hint(url="https://static.mercdn.net/thumb/item/webp/m59827184343_1.jpg?1792584821", **changes):
    value = [url, changes.get("kind", "image"), {"fetchPriority": changes.get("priority", "high")}]
    return ':HL' + json.dumps(value) + '\n'


def script(value):
    return 'self.__next_f.push(' + json.dumps([1, value]) + ')'


class MercariDiscoveryTests(unittest.TestCase):
    def test_exact_public_hint_is_decoded_across_streamed_chunks(self):
        value = hint()
        scripts = [script(value[:25]), script(value[25:])]
        self.assertEqual(preload_product_urls(scripts), ('https://jp.mercari.com/item/m59827184343',))

    def test_unrelated_scripts_secondary_images_and_untrusted_urls_are_ignored(self):
        urls = ['https://static.mercdn.net.evil.invalid/thumb/item/webp/m59827184343_1.jpg',
                'https://user@static.mercdn.net/thumb/item/webp/m59827184343_1.jpg',
                'https://static.mercdn.net:443/thumb/item/webp/m59827184343_1.jpg',
                'https://static.mercdn.net/thumb/item/webp/m59827184343_2.jpg',
                'https://static.mercdn.net/thumb/item/webp/m59827184343_1.jpg?url=private',
                'https://static.mercdn.net/thumb/item/webp/m59827184343_1.jpg#fragment']
        scripts = [script(hint(url)) for url in urls]
        scripts += [script(hint(priority='low')), script(hint(kind='script')),
                    'const image = ' + json.dumps(hint()), script('arbitrary:' + hint())]
        self.assertEqual(preload_product_urls(scripts), ())

    def test_candidate_count_and_input_size_are_bounded(self):
        value = ''.join(hint(f'https://static.mercdn.net/thumb/item/webp/m{10000000+i}_1.jpg') for i in range(5))
        self.assertEqual(len(preload_product_urls([script(value)])), 3)
        self.assertEqual(preload_product_urls(['x' * 1_000_001]), ())
        self.assertEqual(preload_product_urls([script(hint())] * 201), ())


if __name__ == '__main__':
    unittest.main()
