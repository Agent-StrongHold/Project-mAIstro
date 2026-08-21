from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

IFEVAL_SAMPLES: list[dict[str, Any]] = [
    {
        "id": "ife_01",
        "instruction": "Write a short paragraph about renewable energy. You must include the keyword 'solar'.",
        "rules": [{"type": "contains", "value": "solar"}],
    },
    {
        "id": "ife_02",
        "instruction": "Explain machine learning in exactly 3 sentences.",
        "rules": [{"type": "sentence_count", "value": 3, "tolerance": 0}],
    },
    {
        "id": "ife_03",
        "instruction": "List 4 benefits of exercise. Your response must be in JSON format with a 'benefits' array.",
        "rules": [{"type": "valid_json"}, {"type": "json_field", "field": "benefits"}],
    },
    {
        "id": "ife_04",
        "instruction": "Describe the water cycle. Do NOT use the word 'evaporation'.",
        "rules": [{"type": "not_contains", "value": "evaporation"}],
    },
    {
        "id": "ife_05",
        "instruction": "Start your response with the exact phrase: ANSWER:",
        "rules": [{"type": "starts_with", "value": "ANSWER:"}],
    },
    {
        "id": "ife_06",
        "instruction": "Write a haiku about programming. End your response with [END].",
        "rules": [{"type": "ends_with", "value": "[END]"}],
    },
    {
        "id": "ife_07",
        "instruction": "Name 5 programming languages. Format your answer as a numbered list.",
        "rules": [{"type": "contains", "value": "1."}, {"type": "contains", "value": "5."}],
    },
    {
        "id": "ife_08",
        "instruction": "Explain quantum computing. Include both the keywords 'superposition' and 'entanglement'.",
        "rules": [
            {"type": "contains", "value": "superposition"},
            {"type": "contains", "value": "entanglement"},
        ],
    },
    {
        "id": "ife_09",
        "instruction": "Write a function in Python that reverses a string. Wrap the code in ```python``` code blocks.",
        "rules": [{"type": "contains", "value": "```python"}],
    },
    {
        "id": "ife_10",
        "instruction": "Describe the solar system. Your response must be at least 100 words.",
        "rules": [{"type": "min_word_count", "value": 100}],
    },
    {
        "id": "ife_11",
        "instruction": "What is the capital of France? Respond with ONLY the city name, no other text.",
        "rules": [
            {"type": "exact_match", "value": "Paris"},
            {"type": "max_word_count", "value": 2},
        ],
    },
    {
        "id": "ife_12",
        "instruction": "Write a short story about a robot. Include the keyword 'consciousness' and end with [FIN].",
        "rules": [
            {"type": "contains", "value": "consciousness"},
            {"type": "ends_with", "value": "[FIN]"},
        ],
    },
    {
        "id": "ife_13",
        "instruction": "Explain the difference between TCP and UDP. Do NOT use the words 'reliable' or 'unreliable'.",
        "rules": [
            {"type": "not_contains", "value": "reliable"},
            {"type": "not_contains", "value": "unreliable"},
        ],
    },
    {
        "id": "ife_14",
        "instruction": "Create a JSON object with exactly 3 keys: 'name', 'age', and 'city'. The values should be example data.",
        "rules": [
            {"type": "valid_json"},
            {"type": "json_field", "field": "name"},
            {"type": "json_field", "field": "age"},
            {"type": "json_field", "field": "city"},
        ],
    },
    {
        "id": "ife_15",
        "instruction": "Write a limerick about AI. Start your response with the word 'There'.",
        "rules": [{"type": "starts_with", "value": "There"}, {"type": "contains", "value": "AI"}],
    },
    {
        "id": "ife_16",
        "instruction": "Summarize the theory of relativity in exactly 2 sentences. Include the keyword 'spacetime'.",
        "rules": [
            {"type": "sentence_count", "value": 2, "tolerance": 0},
            {"type": "contains", "value": "spacetime"},
        ],
    },
    {
        "id": "ife_17",
        "instruction": "What is 2 + 2? Respond with ONLY the number.",
        "rules": [{"type": "exact_match", "value": "4"}, {"type": "max_word_count", "value": 1}],
    },
    {
        "id": "ife_18",
        "instruction": "List the primary colors. Your response must be in all uppercase letters.",
        "rules": [{"type": "is_uppercase"}],
    },
    {
        "id": "ife_19",
        "instruction": "Write about climate change. Include at least 2 section headers using markdown ## format.",
        "rules": [
            {"type": "contains", "value": "## "},
            {"type": "min_occurrences", "value": "## ", "count": 2},
        ],
    },
    {
        "id": "ife_20",
        "instruction": "Describe how a black hole forms. Do NOT use the words 'dark', 'light', or 'hole' except in the term 'black hole'.",
        "rules": [
            {"type": "contains", "value": "black hole"},
            {"type": "not_contains", "value": "dark"},
            {"type": "max_occurrences", "value": "hole", "count": 3},
        ],
    },
]


BFCL_SAMPLES: list[dict[str, Any]] = [
    {
        "id": "bfcl_01",
        "query": "What is the current weather in Tokyo?",
        "functions": [
            {
                "name": "get_weather",
                "description": "Get current weather for a location",
                "parameters": {
                    "location": "string",
                    "unit": "string (optional: celsius/fahrenheit)",
                },
            },
        ],
        "expected_name": "get_weather",
        "expected_params": {"location": "Tokyo"},
    },
    {
        "id": "bfcl_02",
        "query": "Book a table for 4 people at an Italian restaurant tonight at 7pm.",
        "functions": [
            {
                "name": "book_restaurant",
                "description": "Book a restaurant table",
                "parameters": {
                    "party_size": "integer",
                    "cuisine": "string",
                    "time": "string",
                    "date": "string (optional)",
                },
            },
        ],
        "expected_name": "book_restaurant",
        "expected_params": {"party_size": 4, "cuisine": "Italian"},
    },
    {
        "id": "bfcl_03",
        "query": "Send an email to john@example.com with the subject 'Meeting Update' and body 'The meeting is postponed to Friday.'",
        "functions": [
            {
                "name": "send_email",
                "description": "Send an email",
                "parameters": {"to": "string", "subject": "string", "body": "string"},
            },
        ],
        "expected_name": "send_email",
        "expected_params": {"to": "john@example.com", "subject": "Meeting Update"},
    },
    {
        "id": "bfcl_04",
        "query": "What's 15% tip on a $85.50 bill?",
        "functions": [
            {
                "name": "calculate_tip",
                "description": "Calculate tip amount",
                "parameters": {"bill_amount": "number", "tip_percentage": "number"},
            },
        ],
        "expected_name": "calculate_tip",
        "expected_params": {"bill_amount": 85.50, "tip_percentage": 15},
    },
    {
        "id": "bfcl_05",
        "query": "Find flights from New York to London departing on March 15th.",
        "functions": [
            {
                "name": "search_flights",
                "description": "Search for flights",
                "parameters": {"origin": "string", "destination": "string", "date": "string"},
            },
        ],
        "expected_name": "search_flights",
        "expected_params": {"origin": "New York", "destination": "London"},
    },
    {
        "id": "bfcl_06",
        "query": "Set a timer for 25 minutes called 'Pomodoro'.",
        "functions": [
            {
                "name": "set_timer",
                "description": "Set a countdown timer",
                "parameters": {"duration_minutes": "integer", "label": "string"},
            },
        ],
        "expected_name": "set_timer",
        "expected_params": {"duration_minutes": 25, "label": "Pomodoro"},
    },
    {
        "id": "bfcl_07",
        "query": "Play 'Bohemian Rhapsody' by Queen on Spotify.",
        "functions": [
            {
                "name": "play_music",
                "description": "Play a song on a music service",
                "parameters": {
                    "song": "string",
                    "artist": "string",
                    "service": "string (optional)",
                },
            },
        ],
        "expected_name": "play_music",
        "expected_params": {"song": "Bohemian Rhapsody", "artist": "Queen"},
    },
    {
        "id": "bfcl_08",
        "query": "Convert 100 USD to EUR.",
        "functions": [
            {
                "name": "convert_currency",
                "description": "Convert between currencies",
                "parameters": {
                    "amount": "number",
                    "from_currency": "string",
                    "to_currency": "string",
                },
            },
        ],
        "expected_name": "convert_currency",
        "expected_params": {"amount": 100, "from_currency": "USD", "to_currency": "EUR"},
    },
    {
        "id": "bfcl_09",
        "query": "Add 'Buy groceries' to my todo list with high priority.",
        "functions": [
            {
                "name": "add_todo",
                "description": "Add item to todo list",
                "parameters": {"task": "string", "priority": "string (low/medium/high)"},
            },
        ],
        "expected_name": "add_todo",
        "expected_params": {"task": "Buy groceries", "priority": "high"},
    },
    {
        "id": "bfcl_10",
        "query": "Create a calendar event called 'Team Standup' that repeats every Monday at 9am.",
        "functions": [
            {
                "name": "create_event",
                "description": "Create a calendar event",
                "parameters": {
                    "title": "string",
                    "day": "string",
                    "time": "string",
                    "recurring": "boolean",
                },
            },
        ],
        "expected_name": "create_event",
        "expected_params": {"title": "Team Standup", "day": "Monday", "recurring": True},
    },
    {
        "id": "bfcl_11",
        "query": "Look up the stock price for Apple (AAPL).",
        "functions": [
            {
                "name": "get_stock_price",
                "description": "Get current stock price",
                "parameters": {"symbol": "string"},
            },
        ],
        "expected_name": "get_stock_price",
        "expected_params": {"symbol": "AAPL"},
    },
    {
        "id": "bfcl_12",
        "query": "Translate 'Hello, how are you?' from English to Spanish.",
        "functions": [
            {
                "name": "translate_text",
                "description": "Translate text between languages",
                "parameters": {"text": "string", "source_lang": "string", "target_lang": "string"},
            },
        ],
        "expected_name": "translate_text",
        "expected_params": {"source_lang": "English", "target_lang": "Spanish"},
    },
    {
        "id": "bfcl_13",
        "query": "Turn off the living room lights and set the thermostat to 72 degrees.",
        "functions": [
            {
                "name": "control_lights",
                "description": "Control smart lights",
                "parameters": {"room": "string", "state": "string (on/off)"},
            },
            {
                "name": "set_thermostat",
                "description": "Set thermostat temperature",
                "parameters": {"temperature": "integer", "unit": "string (optional)"},
            },
        ],
        "expected_name": "control_lights",
        "expected_params": {"room": "living room", "state": "off"},
        "extra_call": {"name": "set_thermostat", "params": {"temperature": 72}},
    },
    {
        "id": "bfcl_14",
        "query": "Get directions from my current location to the nearest gas station.",
        "functions": [
            {
                "name": "get_directions",
                "description": "Get navigation directions",
                "parameters": {
                    "origin": "string",
                    "destination": "string",
                    "transport_mode": "string (optional)",
                },
            },
            {
                "name": "find_nearby",
                "description": "Find nearby places",
                "parameters": {"type": "string", "radius_km": "number (optional)"},
            },
        ],
        "expected_name": "find_nearby",
        "expected_params": {"type": "gas station"},
    },
    {
        "id": "bfcl_15",
        "query": "Save a contact named Sarah Johnson with phone 555-0123 and email sarah@company.com.",
        "functions": [
            {
                "name": "save_contact",
                "description": "Save a new contact",
                "parameters": {"name": "string", "phone": "string", "email": "string"},
            },
        ],
        "expected_name": "save_contact",
        "expected_params": {"name": "Sarah Johnson", "phone": "555-0123"},
    },
    {
        "id": "bfcl_16",
        "query": "Order a large pepperoni pizza for delivery to 123 Main St.",
        "functions": [
            {
                "name": "order_pizza",
                "description": "Order pizza delivery",
                "parameters": {"size": "string", "toppings": "array", "delivery_address": "string"},
            },
        ],
        "expected_name": "order_pizza",
        "expected_params": {"size": "large", "delivery_address": "123 Main St"},
    },
    {
        "id": "bfcl_17",
        "query": "Find a hotel in Paris with check-in on June 1st and check-out on June 5th for 2 guests.",
        "functions": [
            {
                "name": "search_hotels",
                "description": "Search for hotels",
                "parameters": {
                    "city": "string",
                    "check_in": "string",
                    "check_out": "string",
                    "guests": "integer",
                },
            },
        ],
        "expected_name": "search_hotels",
        "expected_params": {"city": "Paris", "guests": 2},
    },
    {
        "id": "bfcl_18",
        "query": "Calculate the monthly payment for a 30-year mortgage of $400,000 at 6.5% interest.",
        "functions": [
            {
                "name": "calculate_mortgage",
                "description": "Calculate mortgage payments",
                "parameters": {
                    "principal": "number",
                    "interest_rate": "number",
                    "years": "integer",
                },
            },
        ],
        "expected_name": "calculate_mortgage",
        "expected_params": {"principal": 400000, "interest_rate": 6.5, "years": 30},
    },
    {
        "id": "bfcl_19",
        "query": "Set an alarm for 6:30 AM tomorrow labeled 'Early Meeting'.",
        "functions": [
            {
                "name": "set_alarm",
                "description": "Set an alarm",
                "parameters": {"time": "string", "label": "string", "days": "string (optional)"},
            },
        ],
        "expected_name": "set_alarm",
        "expected_params": {"time": "6:30 AM", "label": "Early Meeting"},
    },
    {
        "id": "bfcl_20",
        "query": "Share the photo from my last vacation on Instagram with caption 'Paradise found'.",
        "functions": [
            {
                "name": "share_photo",
                "description": "Share a photo on social media",
                "parameters": {
                    "platform": "string",
                    "caption": "string",
                    "album": "string (optional)",
                },
            },
        ],
        "expected_name": "share_photo",
        "expected_params": {"platform": "Instagram", "caption": "Paradise found"},
    },
]


GAIA_SAMPLES: list[dict[str, Any]] = [
    {
        "id": "gaia_01",
        "question": "What is the chemical symbol for gold?",
        "answer": "Au",
        "level": 1,
    },
    {
        "id": "gaia_02",
        "question": "In what year did the Berlin Wall fall?",
        "answer": "1989",
        "level": 1,
    },
    {
        "id": "gaia_03",
        "question": "Which planet in our solar system has the most moons?",
        "answer": "Saturn",
        "level": 1,
    },
    {
        "id": "gaia_04",
        "question": "What is the smallest prime number greater than 50?",
        "answer": "53",
        "level": 1,
    },
    {
        "id": "gaia_05",
        "question": "Who wrote '1984' and 'Animal Farm'?",
        "answer": "George Orwell",
        "level": 1,
    },
    {
        "id": "gaia_06",
        "question": "What is the square root of 1764?",
        "answer": "42",
        "level": 1,
    },
    {
        "id": "gaia_07",
        "question": "Which element has the atomic number 79?",
        "answer": "Gold",
        "level": 1,
    },
    {
        "id": "gaia_08",
        "question": "In computer science, what does 'HTTP' stand for?",
        "answer": "HyperText Transfer Protocol",
        "level": 1,
    },
    {
        "id": "gaia_09",
        "question": "If a triangle has two angles of 45 degrees, what is the third angle?",
        "answer": "90",
        "level": 1,
    },
    {
        "id": "gaia_10",
        "question": "What is the capital of the country that hosted the 2016 Summer Olympics?",
        "answer": "Brasilia",
        "level": 2,
    },
    {
        "id": "gaia_11",
        "question": "How many bits are in 3 bytes?",
        "answer": "24",
        "level": 1,
    },
    {
        "id": "gaia_12",
        "question": "What programming language was created by Guido van Rossum?",
        "answer": "Python",
        "level": 1,
    },
    {
        "id": "gaia_13",
        "question": "If you arrange the letters C, A, T, S alphabetically, what is the second letter?",
        "answer": "A",
        "level": 1,
    },
    {
        "id": "gaia_14",
        "question": "What is 17 multiplied by 13?",
        "answer": "221",
        "level": 1,
    },
    {
        "id": "gaia_15",
        "question": "Which ocean is the largest by total area?",
        "answer": "Pacific",
        "level": 1,
    },
]


TAU_BENCH_SAMPLES: list[dict[str, Any]] = [
    {
        "id": "tau_01",
        "scenario": "User wants to check their account balance.",
        "conversation": [
            {"role": "user", "content": "Hi, what is my current account balance?"},
        ],
        "tools": [
            {
                "name": "get_account_balance",
                "description": "Retrieve the user's current account balance",
                "parameters": {},
            },
        ],
        "expected_tool_calls": ["get_account_balance"],
        "max_turns": 3,
    },
    {
        "id": "tau_02",
        "scenario": "User wants to book a flight and check weather at destination.",
        "conversation": [
            {
                "role": "user",
                "content": "I need a flight to Miami next Friday. Also, what's the weather going to be like there?",
            },
        ],
        "tools": [
            {
                "name": "search_flights",
                "description": "Search for flights",
                "parameters": {"destination": "string", "date": "string"},
            },
            {
                "name": "get_weather_forecast",
                "description": "Get weather forecast for a location",
                "parameters": {"location": "string", "date": "string"},
            },
        ],
        "expected_tool_calls": ["search_flights", "get_weather_forecast"],
        "max_turns": 3,
    },
    {
        "id": "tau_03",
        "scenario": "User needs to reset their password.",
        "conversation": [
            {
                "role": "user",
                "content": "I forgot my password and need to reset it. My email is user@test.com.",
            },
        ],
        "tools": [
            {
                "name": "send_password_reset",
                "description": "Send a password reset email",
                "parameters": {"email": "string"},
            },
        ],
        "expected_tool_calls": ["send_password_reset"],
        "max_turns": 3,
    },
    {
        "id": "tau_04",
        "scenario": "User wants to cancel order #12345.",
        "conversation": [
            {"role": "user", "content": "I want to cancel my order number 12345."},
        ],
        "tools": [
            {
                "name": "lookup_order",
                "description": "Look up order details",
                "parameters": {"order_id": "string"},
            },
            {
                "name": "cancel_order",
                "description": "Cancel an order",
                "parameters": {"order_id": "string", "reason": "string"},
            },
        ],
        "expected_tool_calls": ["lookup_order", "cancel_order"],
        "max_turns": 4,
    },
    {
        "id": "tau_05",
        "scenario": "User asks about return policy and wants to return an item.",
        "conversation": [
            {
                "role": "user",
                "content": "What is your return policy? I bought a shirt 5 days ago and want to return it. Order number is 67890.",
            },
        ],
        "tools": [
            {
                "name": "get_return_policy",
                "description": "Get the current return policy",
                "parameters": {},
            },
            {
                "name": "initiate_return",
                "description": "Start a return process",
                "parameters": {"order_id": "string", "item": "string", "reason": "string"},
            },
        ],
        "expected_tool_calls": ["get_return_policy", "initiate_return"],
        "max_turns": 5,
    },
    {
        "id": "tau_06",
        "scenario": "User wants to schedule a meeting with multiple participants.",
        "conversation": [
            {
                "role": "user",
                "content": "Schedule a 1-hour meeting with Alice and Bob for tomorrow at 2pm. Topic: Q3 review.",
            },
        ],
        "tools": [
            {
                "name": "check_availability",
                "description": "Check calendar availability for attendees",
                "parameters": {"attendees": "array", "date": "string", "time": "string"},
            },
            {
                "name": "create_meeting",
                "description": "Create a calendar meeting",
                "parameters": {
                    "title": "string",
                    "attendees": "array",
                    "date": "string",
                    "time": "string",
                    "duration_minutes": "integer",
                },
            },
        ],
        "expected_tool_calls": ["check_availability", "create_meeting"],
        "max_turns": 4,
    },
    {
        "id": "tau_07",
        "scenario": "User reports a bug and wants to file a support ticket.",
        "conversation": [
            {
                "role": "user",
                "content": "The app keeps crashing when I try to upload photos. Can you help? I'm on version 3.2.1, Android.",
            },
        ],
        "tools": [
            {
                "name": "create_support_ticket",
                "description": "Create a support ticket",
                "parameters": {
                    "description": "string",
                    "app_version": "string",
                    "platform": "string",
                    "severity": "string",
                },
            },
            {
                "name": "check_known_issues",
                "description": "Check if issue is known",
                "parameters": {"keywords": "string"},
            },
        ],
        "expected_tool_calls": ["check_known_issues", "create_support_ticket"],
        "max_turns": 4,
    },
    {
        "id": "tau_08",
        "scenario": "User wants to update shipping address for a pending order.",
        "conversation": [
            {
                "role": "user",
                "content": "I just moved and need to update the shipping address for my order 55555 to 456 Oak Ave, Portland, OR 97201.",
            },
        ],
        "tools": [
            {
                "name": "lookup_order",
                "description": "Look up order details",
                "parameters": {"order_id": "string"},
            },
            {
                "name": "update_shipping_address",
                "description": "Update shipping address for an order",
                "parameters": {
                    "order_id": "string",
                    "address": "string",
                    "city": "string",
                    "state": "string",
                    "zip": "string",
                },
            },
        ],
        "expected_tool_calls": ["lookup_order", "update_shipping_address"],
        "max_turns": 4,
    },
    {
        "id": "tau_09",
        "scenario": "User wants product recommendation within budget.",
        "conversation": [
            {
                "role": "user",
                "content": "I'm looking for a laptop under $800 with at least 16GB RAM. What do you recommend?",
            },
        ],
        "tools": [
            {
                "name": "search_products",
                "description": "Search for products matching criteria",
                "parameters": {"category": "string", "max_price": "number", "specs": "object"},
            },
        ],
        "expected_tool_calls": ["search_products"],
        "max_turns": 3,
    },
    {
        "id": "tau_10",
        "scenario": "User wants to set up recurring transfer.",
        "conversation": [
            {
                "role": "user",
                "content": "Set up a monthly transfer of $500 from my checking to my savings account on the 1st of every month.",
            },
        ],
        "tools": [
            {"name": "list_accounts", "description": "List user's bank accounts", "parameters": {}},
            {
                "name": "create_recurring_transfer",
                "description": "Create a recurring transfer",
                "parameters": {
                    "from_account": "string",
                    "to_account": "string",
                    "amount": "number",
                    "frequency": "string",
                    "day": "integer",
                },
            },
        ],
        "expected_tool_calls": ["list_accounts", "create_recurring_transfer"],
        "max_turns": 4,
    },
    {
        "id": "tau_11",
        "scenario": "User asks about restaurant recommendations and wants to make a reservation.",
        "conversation": [
            {
                "role": "user",
                "content": "Find Italian restaurants near downtown Seattle and book a table for 2 at 7pm tonight.",
            },
        ],
        "tools": [
            {
                "name": "search_restaurants",
                "description": "Search for nearby restaurants",
                "parameters": {"cuisine": "string", "location": "string"},
            },
            {
                "name": "book_restaurant",
                "description": "Book a restaurant table",
                "parameters": {
                    "restaurant_id": "string",
                    "party_size": "integer",
                    "time": "string",
                    "date": "string",
                },
            },
        ],
        "expected_tool_calls": ["search_restaurants", "book_restaurant"],
        "max_turns": 4,
    },
    {
        "id": "tau_12",
        "scenario": "User wants to subscribe to a newsletter and get a confirmation.",
        "conversation": [
            {
                "role": "user",
                "content": "Sign me up for the weekly tech newsletter at my email: dev@startup.io",
            },
        ],
        "tools": [
            {
                "name": "subscribe_newsletter",
                "description": "Subscribe user to a newsletter",
                "parameters": {"email": "string", "newsletter_type": "string"},
            },
        ],
        "expected_tool_calls": ["subscribe_newsletter"],
        "max_turns": 3,
    },
]


SWEBENCH_SAMPLES: list[dict[str, Any]] = [
    {
        "id": "swe_01",
        "problem": "The function `flatten_list` in utils.py does not handle nested lists deeper than 2 levels. Fix it to handle arbitrary nesting.",
        "buggy_code": "def flatten_list(lst):\n    result = []\n    for item in lst:\n        if isinstance(item, list):\n            result.extend(item)\n        else:\n            result.append(item)\n    return result",
        "expected_keywords": ["recursive", "isinstance", "extend", "flatten"],
        "test_input": "[[1, [2, 3]], [4, [5, [6]]]]",
        "expected_output": "[1, 2, 3, 4, 5, 6]",
        "call_args": [[[1, [2, 3]], [4, [5, [6]]]]],
        "expected_value": [1, 2, 3, 4, 5, 6],
    },
    {
        "id": "swe_02",
        "problem": "The `validate_email` function accepts emails without a domain. Fix it to require a valid domain with at least one dot.",
        "buggy_code": "def validate_email(email):\n    return '@' in email",
        "expected_keywords": ["@", ".", "split"],
        "test_input": "'test@com'",
        "expected_output": "False",
        "call_args": ["test@com"],
        "expected_value": False,
    },
    {
        "id": "swe_03",
        "problem": "The `merge_dicts` function overwrites values instead of merging nested dicts. Fix it to recursively merge.",
        "buggy_code": "def merge_dicts(a, b):\n    result = a.copy()\n    result.update(b)\n    return result",
        "expected_keywords": ["isinstance", "dict", "recursive"],
        "test_input": "({'a': {'b': 1, 'c': 2}}, {'a': {'b': 3, 'd': 4}})",
        "expected_output": "{'a': {'b': 3, 'c': 2, 'd': 4}}",
        "call_args": [{"a": {"b": 1, "c": 2}}, {"a": {"b": 3, "d": 4}}],
        "expected_value": {"a": {"b": 3, "c": 2, "d": 4}},
    },
    {
        "id": "swe_04",
        "problem": "The `parse_date` function fails to handle ISO 8601 dates with timezone info. Fix it.",
        "buggy_code": "from datetime import datetime\ndef parse_date(date_str):\n    return datetime.strptime(date_str, '%Y-%m-%d')",
        "expected_keywords": ["fromisoformat", "timezone", "strptime"],
        "test_input": "'2024-01-15T10:30:00+00:00'",
        "expected_output": "datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)",
        "call_args": ["2024-01-15T10:30:00+00:00"],
        "expected_value": datetime(2024, 1, 15, 10, 30, tzinfo=UTC),
    },
    {
        "id": "swe_05",
        "problem": "The `chunk_list` function drops the last chunk if it's smaller than the chunk size. Fix it to include remaining elements.",
        "buggy_code": "def chunk_list(lst, size):\n    return [lst[i:i+size] for i in range(0, len(lst), size) if len(lst[i:i+size]) == size]",
        "expected_keywords": ["range", "len", "lst"],
        "test_input": "([1, 2, 3, 4, 5], 2)",
        "expected_output": "[[1, 2], [3, 4], [5]]",
        "call_args": [[1, 2, 3, 4, 5], 2],
        "expected_value": [[1, 2], [3, 4], [5]],
    },
    {
        "id": "swe_06",
        "problem": "The `count_words` function doesn't handle punctuation correctly, counting 'hello,' and 'hello' as different words. Fix it.",
        "buggy_code": "def count_words(text):\n    words = text.split()\n    counts = {}\n    for w in words:\n        counts[w] = counts.get(w, 0) + 1\n    return counts",
        "expected_keywords": ["strip", "lower", "punctuation"],
        "test_input": "'Hello, hello! World. world?'",
        "expected_output": "{'hello': 2, 'world': 2}",
        "call_args": ["Hello, hello! World. world?"],
        "expected_value": {"hello": 2, "world": 2},
    },
    {
        "id": "swe_07",
        "problem": "The `safe_divide` function crashes when denominator is a string representation of zero. Fix it.",
        "buggy_code": "def safe_divide(a, b):\n    try:\n        return a / b\n    except ZeroDivisionError:\n        return None",
        "expected_keywords": ["float", "ZeroDivisionError", "ValueError"],
        "test_input": "(10, '0')",
        "expected_output": "None",
        "call_args": [10, "0"],
        "expected_value": None,
    },
    {
        "id": "swe_08",
        "problem": "The `deduplicate` function preserves insertion order but is O(n^2). Make it O(n) while preserving order.",
        "buggy_code": "def deduplicate(lst):\n    result = []\n    for item in lst:\n        if item not in result:\n            result.append(item)\n    return result",
        "expected_keywords": ["set", "seen", "dict"],
        "test_input": "[3, 1, 2, 3, 2, 1, 4]",
        "expected_output": "[3, 1, 2, 4]",
        # The stated bug is complexity, not correctness — the O(n^2) original
        # already returns the right answer on small input, so a small
        # call_args/expected_value pair (matching test_input/expected_output
        # above, which stay small for the prompt shown to the model) couldn't
        # ever fail it. call_args here is deliberately large enough (120k
        # elements, 60k unique, real duplicates) that an O(n^2) "fix" reliably
        # exceeds run_function_check's default 10s timeout (~19s measured)
        # while a real O(n) fix finishes in milliseconds — the timeout is the
        # check, same mechanism swe_10 (fibonacci) already relies on.
        "call_args": [[i % 60_000 for i in range(120_000)]],
        "expected_value": list(range(60_000)),
    },
    {
        "id": "swe_09",
        "problem": "The `camel_to_snake` function only converts the first word. Fix it to handle the entire string.",
        "buggy_code": "import re\ndef camel_to_snake(name):\n    return re.sub(r'([A-Z])', r'_\\1', name).lstrip('_').lower()[:name.index(next(c for c in name if c.isupper()))] if any(c.isupper() for c in name) else name",
        "expected_keywords": ["re", "sub", "lower"],
        "test_input": "'myCamelCaseString'",
        "expected_output": "'my_camel_case_string'",
        "call_args": ["myCamelCaseString"],
        "expected_value": "my_camel_case_string",
    },
    {
        "id": "swe_10",
        "problem": "The `fibonacci` function is exponentially slow. Optimize it to handle n up to 1000.",
        "buggy_code": "def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)",
        "expected_keywords": ["memo", "cache", "iter", "dict", "loop"],
        "test_input": "100",
        "expected_output": "354224848179261915075",
        "call_args": [100],
        "expected_value": 354224848179261915075,
    },
]


RAGAS_SAMPLES: list[dict[str, Any]] = [
    {
        "id": "rag_01",
        "context": "The Eiffel Tower was completed in 1889 for the World's Fair. It stands 330 meters tall and was designed by Gustave Eiffel. Originally criticized by many of France's leading artists, it has since become a global cultural icon.",
        "question": "Who designed the Eiffel Tower and when was it completed?",
        "expected_answer": "Gustave Eiffel designed it, and it was completed in 1889.",
        "eval_type": "faithfulness",
    },
    {
        "id": "rag_02",
        "context": "Python was created by Guido van Rossum and first released in 1991. It emphasizes code readability with significant whitespace. Python 3.0 was released in 2008.",
        "question": "When was Python first released and by whom?",
        "expected_answer": "Python was first released in 1991 by Guido van Rossum.",
        "eval_type": "faithfulness",
    },
    {
        "id": "rag_03",
        "context": "The mitochondria are membrane-bound organelles found in the cytoplasm of eukaryotic cells. They are often called the 'powerhouse of the cell' because they generate most of the cell's supply of ATP, used as chemical energy.",
        "question": "Why are mitochondria called the powerhouse of the cell?",
        "expected_answer": "Because they generate most of the cell's supply of ATP, which is used as chemical energy.",
        "eval_type": "faithfulness",
    },
    {
        "id": "rag_04",
        "context": "Docker containers are lightweight, standalone packages that include everything needed to run a piece of software, including the code, libraries, and system tools. Unlike virtual machines, containers share the host OS kernel.",
        "question": "What is the key difference between Docker containers and virtual machines?",
        "expected_answer": "Containers share the host OS kernel, unlike virtual machines which have their own full OS.",
        "eval_type": "relevance",
    },
    {
        "id": "rag_05",
        "context": "The Great Wall of China was built over many centuries, beginning around 7th century BC. The most well-known sections were built during the Ming Dynasty (1368-1644). It stretches over 13,000 miles.",
        "question": "How long is the Great Wall of China?",
        "expected_answer": "Over 13,000 miles.",
        "eval_type": "faithfulness",
    },
    {
        "id": "rag_06",
        "context": "Machine learning is a subset of artificial intelligence. Deep learning is a subset of machine learning that uses neural networks with multiple layers. Neural networks are inspired by the human brain's structure.",
        "question": "What is the relationship between AI, machine learning, and deep learning?",
        "expected_answer": "ML is a subset of AI, and deep learning is a subset of ML that uses multi-layer neural networks.",
        "eval_type": "relevance",
    },
    {
        "id": "rag_07",
        "context": "HTTP status code 200 means success. 301 means permanent redirect. 404 means not found. 500 means internal server error. 403 means forbidden.",
        "question": "What does HTTP status code 404 mean?",
        "expected_answer": "Not found.",
        "eval_type": "faithfulness",
    },
    {
        "id": "rag_08",
        "context": "Git branches allow developers to work on features independently. The main branch is typically called 'main' or 'master'. Merging combines branches. Rebasing replays commits on top of another branch.",
        "question": "What is the difference between git merge and git rebase?",
        "expected_answer": "Merge combines branches while preserving history. Rebase replays commits on top of another branch for a linear history.",
        "eval_type": "relevance",
    },
    {
        "id": "rag_09",
        "context": "The speed of light in vacuum is approximately 299,792,458 meters per second. Light travels slower in other media like water or glass. The speed of light is a fundamental constant in physics, denoted as 'c'.",
        "question": "What is the speed of light and why is it important?",
        "expected_answer": "The speed of light is approximately 299,792,458 m/s. It's a fundamental constant in physics, denoted as 'c'.",
        "eval_type": "relevance",
    },
    {
        "id": "rag_10",
        "context": "PostgreSQL supports both JSON and JSONB data types. JSONB stores data in a binary format, making it faster to query but slower to insert. JSON stores text as-is. JSONB supports indexing with GIN indexes.",
        "question": "What is the difference between JSON and JSONB in PostgreSQL?",
        "expected_answer": "JSON stores text as-is while JSONB uses a binary format. JSONB is faster to query (supports GIN indexing) but slower to insert.",
        "eval_type": "faithfulness",
    },
    {
        "id": "rag_11",
        "context": "Recursion is when a function calls itself. Base cases stop the recursion. Without a base case, recursion leads to stack overflow. Python has a default recursion limit of 1000.",
        "question": "What happens if a recursive function has no base case?",
        "expected_answer": "It leads to stack overflow because the recursion never stops.",
        "eval_type": "faithfulness",
    },
    {
        "id": "rag_12",
        "context": "Redis is an in-memory data structure store used as a database, cache, and message broker. It supports data structures like strings, hashes, lists, and sets. Data can optionally be persisted to disk.",
        "question": "What is Redis and what data structures does it support?",
        "expected_answer": "Redis is an in-memory data structure store used as database, cache, and message broker. It supports strings, hashes, lists, and sets.",
        "eval_type": "relevance",
    },
]


OSWORLD_SAMPLES: list[dict[str, Any]] = [
    {
        "id": "osw_01",
        "task": "Open the file manager and navigate to the Documents folder",
        "expected_actions": ["open_file_manager", "navigate_to:Documents"],
        "eval_type": "action_sequence",
    },
    {
        "id": "osw_02",
        "task": "Create a new folder called 'Projects' on the Desktop",
        "expected_actions": ["navigate_to:Desktop", "create_folder:Projects"],
        "eval_type": "action_sequence",
    },
    {
        "id": "osw_03",
        "task": "Change the desktop wallpaper to a nature image",
        "expected_actions": ["open_settings", "navigate_to:wallpaper", "select_category:nature"],
        "eval_type": "action_sequence",
    },
    {
        "id": "osw_04",
        "task": "Install Python 3 using the terminal",
        "expected_actions": ["open_terminal", "run_command:sudo apt install python3"],
        "eval_type": "action_sequence",
    },
    {
        "id": "osw_05",
        "task": "Copy the file 'report.pdf' from Downloads to Documents",
        "expected_actions": [
            "navigate_to:Downloads",
            "select_file:report.pdf",
            "copy",
            "navigate_to:Documents",
            "paste",
        ],
        "eval_type": "action_sequence",
    },
    {
        "id": "osw_06",
        "task": "Open the browser and search for 'climate change statistics'",
        "expected_actions": [
            "open_browser",
            "type_in_search_bar:climate change statistics",
            "press_enter",
        ],
        "eval_type": "action_sequence",
    },
    {
        "id": "osw_07",
        "task": "Connect to a WiFi network called 'HomeNetwork'",
        "expected_actions": ["open_network_settings", "select_wifi:HomeNetwork", "enter_password"],
        "eval_type": "action_sequence",
    },
    {
        "id": "osw_08",
        "task": "Take a screenshot of the entire screen and save it to Pictures",
        "expected_actions": ["press_key:print_screen", "save_to:Pictures"],
        "eval_type": "action_sequence",
    },
    {
        "id": "osw_09",
        "task": "Unzip the file 'archive.zip' in the current directory",
        "expected_actions": ["open_terminal", "run_command:unzip archive.zip"],
        "eval_type": "action_sequence",
    },
    {
        "id": "osw_10",
        "task": "Set the system volume to 50%",
        "expected_actions": ["open_volume_control", "set_volume:50"],
        "eval_type": "action_sequence",
    },
]
