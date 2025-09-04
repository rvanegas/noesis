"""
API endpoint integration tests for argument operations.
These tests ensure the full request → schema → service → response flow works correctly.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from main import app
from schemas.step import Step

client = TestClient(app)


class TestAPIArgumentEndpoints:
    """Test API argument endpoints with full integration"""

    def test_argue_endpoint(self):
        """Test the /api/argument/argue endpoint"""
        # Mock the coordinator to avoid actual agent queuing
        with patch('services.agent_coordinator.coordinator.queue_task') as mock_queue:
            response = client.post(
                "/api/argument/argue",
                params={
                    "conversation_id": "test_session_123:1",
                    "snapshot_id": "test_snapshot_123"
                },
                json={
                    "proposition": "Socrates is mortal",
                    "assumptions": [],
                    "argument": [],
                    "file_ids": []
                }
            )
            
            assert response.status_code == 200
            result = response.json()
            assert "reply" in result
            
            # Verify the coordinator was called
            mock_queue.assert_called()

    def test_gen_name_endpoint(self):
        """Test the /api/argument/gen-name endpoint"""
        with patch('services.conversation.gpt_gen_name.call') as mock_gen_name:
            mock_gen_name.return_value = "Socrates Mortality Argument"
            
            response = client.post(
                "/api/argument/gen-name",
                params={
                    "conversation_id": "test_session_123:1",
                    "snapshot_id": "test_snapshot_123"
                },
                json={
                    "proposition": "Socrates is mortal",
                    "assumptions": [],
                    "argument": [],
                    "file_ids": []
                }
            )
            
            assert response.status_code == 200
            result = response.json()
            assert "reply" in result
            assert result["reply"] == "Socrates Mortality Argument"

    def test_remove_endpoint(self):
        """Test the /api/argument/remove endpoint"""
        with patch('services.agent_coordinator.coordinator.queue_task') as mock_queue:
            response = client.post(
                "/api/argument/remove",
                params={
                    "conversation_id": "test_session_123:1",
                    "snapshot_id": "test_snapshot_123"
                },
                json={
                    "assumptions": [],
                    "argument": [
                        {
                            "symbol": "A",
                            "proposition": "Socrates is a man",
                            "justifiers": [],
                            "truth_score": "1.0",
                            "content_validity": "1.0",
                            "formal_validity": "1.0"
                        },
                        {
                            "symbol": "B",
                            "proposition": "All men are mortal",
                            "justifiers": ["A"],
                            "truth_score": "1.0",
                            "content_validity": "1.0",
                            "formal_validity": "1.0"
                        }
                    ],
                    "loc": "argument",
                    "index": 1,
                    "file_ids": []
                }
            )
            
            assert response.status_code == 200
            result = response.json()
            assert "reply" in result
            
            # Verify the coordinator was called
            mock_queue.assert_called()

    def test_assume_endpoint(self):
        """Test the /api/argument/assume endpoint"""
        with patch('services.agent_coordinator.coordinator.queue_task') as mock_queue:
            response = client.post(
                "/api/argument/assume",
                params={
                    "conversation_id": "test_session_123:1",
                    "snapshot_id": "test_snapshot_123"
                },
                json={
                    "assumptions": [],
                    "argument": [
                        {
                            "symbol": "A",
                            "proposition": "Socrates is a man",
                            "justifiers": [],
                            "truth_score": "0.8",
                            "content_validity": "0.9",
                            "formal_validity": "0.9"
                        }
                    ],
                    "loc": "argument",
                    "index": 0,
                    "file_ids": []
                }
            )
            
            assert response.status_code == 200
            result = response.json()
            assert "reply" in result
            
            # Verify the coordinator was called
            mock_queue.assert_called()

    # DISABLED: Old ai-justify endpoint test - replaced by new agent system
    # def test_ai_justify_endpoint(self):
    #     """Test the /api/argument/ai-justify endpoint"""
    #     with patch('services.agent_coordinator.coordinator.queue_task') as mock_queue:
    #         with patch('services.conversation.gpt_justify.call') as mock_justify:
    #             mock_justify.return_value = '{"propositions": ["All men are mortal"]}'
    #             
    #             response = client.post(
    #                 "/api/argument/ai-justify",
    #                 params={
    #                 "conversation_id": "test_session_123:1",
    #                 "snapshot_id": "test_snapshot_123"
    #             },
    #             json={
    #                 "assumptions": [],
    #                 "argument": [
    #                     {
    #                         "symbol": "A",
    #                         "proposition": "Socrates is mortal",
    #                         "justifiers": [],
    #                         "truth": "0.8",
    #                         "valid": "0.9"
    #                     }
    #                 ],
    #                 "loc": "argument",
    #                 "index": 0,
    #                 "file_ids": []
    #             }
    #         )
    #             
    #         assert response.status_code == 200
    #         result = response.json()
    #         assert "reply" in result
    #             
    #         # Verify both services were called
    #         mock_queue.assert_called()
    #         mock_justify.assert_called()

    def test_user_justify_endpoint(self):
        """Test the /api/argument/user-justify endpoint"""
        with patch('services.agent_coordinator.coordinator.queue_task') as mock_queue:
            response = client.post(
                "/api/argument/user-justify",
                params={
                    "conversation_id": "test_session_123:1",
                    "snapshot_id": "test_snapshot_123"
                },
                json={
                    "assumptions": [],
                    "argument": [
                        {
                            "symbol": "A",
                            "proposition": "Socrates is mortal",
                            "justifiers": [],
                            "truth_score": "0.8",
                            "content_validity": "0.9",
                            "formal_validity": "0.9"
                        }
                    ],
                    "loc": "argument",
                    "index": 0,
                    "proposition": "All men are mortal",
                    "file_ids": []
                }
            )
            
            assert response.status_code == 200
            result = response.json()
            assert "reply" in result
            
            # Verify the coordinator was called
            mock_queue.assert_called()

    def test_explain_endpoint(self):
        """Test the /api/argument/explain endpoint"""
        with patch('services.conversation.gpt_explain.call') as mock_explain:
            mock_explain.return_value = '{"explanation": "This is a valid syllogism"}'
            
            response = client.post(
                "/api/argument/explain",
                params={
                    "conversation_id": "test_session_123:1",
                    "snapshot_id": "test_snapshot_123"
                },
                json={
                    "assumptions": [],
                    "argument": [
                        {
                            "symbol": "A",
                            "proposition": "Socrates is a man",
                            "justifiers": [],
                            "truth_score": "1.0",
                            "content_validity": "1.0",
                            "formal_validity": "1.0"
                        },
                        {
                            "symbol": "B",
                            "proposition": "Socrates is mortal",
                            "justifiers": ["A"],
                            "truth_score": "1.0",
                            "content_validity": "1.0",
                            "formal_validity": "1.0"
                        }
                    ],
                    "loc": "argument",
                    "index": 1,
                    "file_ids": []
                }
            )
            
            assert response.status_code == 200
            result = response.json()
            assert "reply" in result
            
            # Verify the explain service was called
            mock_explain.assert_called()

    # DISABLED: Old evaluate endpoint test - replaced by new agent system
    # def test_evaluate_endpoint(self):
    #     """Test the /api/argument/evaluate endpoint"""
    #     with patch('services.conversation.gpt_evaluate.call') as mock_evaluate:
    #         mock_evaluate.return_value = '{"truth": ["1.0", "1.0"], "valid": "1.0"}'
    #         
    #         response = client.post(
    #             "/api/argument/evaluate",
    #             params={
    #                 "conversation_id": "test_session_123:1",
    #                 "snapshot_id": "test_snapshot_123"
    #             },
    #             json={
    #                 "assumptions": [],
    #                 "argument": [
    #                     {
    #                         "symbol": "A",
    #                         "proposition": "Socrates is a man",
    #                         "justifiers": [],
    #                         "truth": "0.8",
    #                         "valid": "0.9"
    #                     },
    #                     {
    #                         "symbol": "B",
    #                         "proposition": "Socrates is mortal",
    #                         "justifiers": ["A"],
    #                         "truth": "0.8",
    #                         "valid": "0.9"
    #                     }
    #                 ],
    #                 "file_ids": []
    #             }
    #         )
    #         
    #         assert response.status_code == 200
    #         result = response.json()
    #         assert "reply" in result
    #         
    #         # Verify the evaluate service was called
    #         mock_evaluate.assert_called()

    def test_upload_endpoint(self):
        """Test the /api/argument/upload endpoint"""
        with patch('api.argument.create_file') as mock_create_file:
            mock_create_file.return_value = {"file_id": "test_file_ref", "filename": "test.txt"}
            
            # Create a test file
            test_content = b"Test file content"
            response = client.post(
                "/api/argument/upload",
                files={"file": ("test.txt", test_content, "text/plain")}
            )
            
            assert response.status_code == 200
            result = response.json()
            assert "reply" in result
            assert result["reply"] == {"file_id": "test_file_ref", "filename": "test.txt"}
            
            # Verify the file service was called
            mock_create_file.assert_called_once()

    def test_missing_session_id(self):
        """Test that missing session_id returns 422"""
        response = client.post(
            "/api/argument/argue",
            json={
                "proposition": "Socrates is mortal",
                "assumptions": [],
                "argument": [],
                "file_ids": []
            }
        )
        
        assert response.status_code == 422

    def test_missing_conversation_id(self):
        """Test that missing conversation_id returns 422"""
        response = client.post(
            "/api/argument/argue",
            params={"session_id": "test_session_123"},
            json={
                "proposition": "Socrates is mortal",
                "assumptions": [],
                "argument": [],
                "file_ids": []
            }
        )
        
        assert response.status_code == 422

    def test_invalid_argument_data(self):
        """Test that invalid argument data returns 422"""
        response = client.post(
            "/api/argument/argue",
            params={
                "session_id": "test_session_123",
                "conversation_id": "1"
            },
            json={
                "proposition": "Socrates is mortal",
                # Missing required fields
                "assumptions": "invalid_type",  # Should be list
                "argument": "invalid_type"      # Should be list
            }
        )
        
        assert response.status_code == 422


class TestAPIErrorHandling:
    """Test API error handling and edge cases"""

    def test_service_exception_handling(self):
        """Test that service exceptions are properly handled"""
        # This test would need proper exception handling in the API layer
        # For now, we'll skip it since the current API doesn't handle service exceptions
        pytest.skip("API layer doesn't currently handle service exceptions")

    def test_validation_error_handling(self):
        """Test that validation errors are properly handled"""
        response = client.post(
            "/api/argument/argue",
            params={
                "session_id": "test_session_123",
                "conversation_id": "1"
            },
            json={
                # Missing required proposition field
                "assumptions": [],
                "argument": [],
                "file_ids": []
            }
        )
        
        assert response.status_code == 422
        result = response.json()
        assert "detail" in result
