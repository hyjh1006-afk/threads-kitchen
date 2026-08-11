# -*- coding: utf-8 -*-
import unittest

import blog_content
import blog_recipe_publisher


MENU = {
    "id": "m99",
    "name": "테스트 집밥",
    "body": "바쁜 날 해먹기 좋은 메뉴",
    "recipe": "재료를 섞고 익혀서 완성",
    "ingredients": [],
}


def expansion(text: str = "담백한 설명") -> dict:
    sentence = (text + "을 원문 범위 안에서 차근차근 설명해볼게. ") * 2
    return {
        "opening": [sentence, sentence],
        "why": [sentence, sentence, sentence],
        "tips": [sentence, sentence, sentence],
        "uses": [sentence, sentence],
        "closing": sentence,
    }


class LongFormTests(unittest.TestCase):
    def test_grounded_expansion_accepts_no_new_numbers(self):
        self.assertTrue(blog_content._valid(expansion(), MENU["body"] + "\n" + MENU["recipe"]))

    def test_expansion_rejects_new_number(self):
        data = expansion()
        data["tips"][0] += " 180도에서 익혀."
        self.assertFalse(blog_content._valid(data, MENU["body"] + "\n" + MENU["recipe"]))

    def test_article_has_blog_sections(self):
        article = blog_recipe_publisher.build_article(
            MENU, [], [], "고지", expansion()
        )
        self.assertIn("왜 이 방식이 편하냐면", article)
        self.assertIn("재료와 만드는 순서", article)
        self.assertIn("실패를 줄이는 포인트", article)
        self.assertIn("이렇게 활용해도 좋아", article)


if __name__ == "__main__":
    unittest.main()
