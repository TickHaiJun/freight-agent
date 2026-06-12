import unittest

from langchain_core.messages import HumanMessage

from graph.nodes import intent_node


def build_state(message: str, **overrides):
    state = {
        "messages": [HumanMessage(content=message)],
        "intent": None,
        "query_subtype": None,
        "response_mode": None,
        "quantity_mode": None,
        "sfg": None,
        "mdg": None,
        "inputWeight": None,
        "inputVol": None,
        "hbrq": None,
        "hbrqBegin": None,
        "hbrqEnd": None,
        "flightType": None,
        "packageType": None,
        "cargoType": None,
        "twoCode": None,
        "gid": None,
        "missing_slots": [],
        "query_ready": False,
        "query_completed": False,
        "reset_quote_context": False,
        "current_beijing_date": "2026-06-09",
        "time_clarify_message": None,
        "pending_clarify_slot": None,
        "pending_clarify_message": None,
        "pending_clarify_context": None,
        "pending_action_type": None,
        "pending_action_prompt": None,
        "pending_action_payload": None,
        "pending_action_retry_count": 0,
        "pending_reuse_confirmation": False,
        "pending_reuse_message": None,
        "reuse_candidate_context": None,
        "reuse_confirmation_decision": None,
        "result_display_mode": None,
        "api_result": None,
        "api_error": None,
        "quote_result_active": False,
        "latest_quote_result": None,
        "result_analysis_intent": None,
        "result_analysis_filters": None,
        "result_reference_field": None,
        "result_reference_request": None,
        "support_info_kind": None,
        "rag_query": None,
        "retrieval_query": None,
        "retrieval_filters": None,
        "retrieved_docs": None,
        "rag_answer": None,
    }
    state.update(overrides)
    return state


class IntentRoutingTests(unittest.TestCase):
    def test_all_origin_scope_question_routes_to_support_info(self):
        result = intent_node(build_state("全部港口有哪些"))

        self.assertEqual(result["intent"], "support_info")
        self.assertEqual(result["support_info_kind"], "all_origin_scope")

    def test_business_meta_question_routes_to_support_info(self):
        result = intent_node(build_state("你不问我始发港是哪里吗", missing_slots=["sfg"]))

        self.assertEqual(result["intent"], "support_info")
        self.assertEqual(result["support_info_kind"], "business_meta")

    def test_explicit_new_quote_beats_result_reference(self):
        result = intent_node(
            build_state(
                "我有一票货，从南京，上海，发往洛杉矶 890公斤 9个立方，托盘，今天发货多少钱",
                query_completed=True,
                quote_result_active=True,
                latest_quote_result={"quote_list": [{"price_total": 123}]},
                sfg="can",
                mdg="lax",
                inputWeight=500,
                inputVol=4,
                packageType="散货",
                hbrq="2026-06-08",
            )
        )

        self.assertEqual(result["intent"], "rate_query")
        self.assertEqual(result["query_subtype"], "new_quote")
        self.assertFalse(result["quote_result_active"])

    def test_smalltalk_does_not_route_to_unknown(self):
        result = intent_node(build_state("谢谢"))

        self.assertEqual(result["intent"], "support_info")
        self.assertEqual(result["support_info_kind"], "smalltalk")


if __name__ == "__main__":
    unittest.main()
