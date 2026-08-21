"""Creative Writing — Children's Books DAGs — grounded in REAL authors.

Every story uses real published authors as the quality benchmark.
The clarify node asks which authors to emulate. The writing nodes
reference specific techniques from those authors.
"""

DAGS = [
    {
        "id": "cw_picture_book",
        "name": "Picture Book",
        "department": "creative_writing",
        "description": "100-300 words, ages 2-5, in the style of real picture book masters",
        "nodes": [
            {
                "id": "clarify",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "interviewer",
                "tool": "clarify",
                "tool_config": {
                    "questions": [
                        "How old is the child this is for? (This determines vocabulary, sentence length, and which proven styles we'll use.)",
                        "What is the main character? (animal, child, object) Describe their appearance and one defining personality trait.",
                        "What is the emotional journey? (e.g., scared→brave, lonely→connected, confused→understanding)",
                        "What is the setting? Describe the world in sensory detail — colors, sounds, textures.",
                        "What is the single concept or lesson? (e.g., sharing, bedtime routine, counting, colors)",
                        "What should the tone be? (silly/funny, warm/gentle, exciting/adventurous, interactive/participatory)",
                    ]
                },
            },
            {
                "id": "research",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {
                    "queries_from_input": True,
                    "query_template": "{input} picture book writing techniques craft",
                    "max_results": 3,
                },
            },
            {
                "id": "structure",
                "prompt": "Plan a 12-page picture book spread-by-spread. Study these REAL examples of what good looks like:\n\nDr. Seuss (Green Eggs and Ham):\n'I do not like green eggs and ham. I do not like them, Sam-I-Am.'\nRules: Rhyme drives plot, limited vocabulary, repetition with variation, absurdity escalates.\n\nEric Carle (The Very Hungry Caterpillar):\n'On Monday he ate through one apple. But he was still hungry.'\nRules: Cumulative pattern, same structure with one variable changed, child predicts the pattern.\n\nMo Willems (Elephant & Piggie):\n'Gerald: I am sad. Piggie: Why? Gerald: I cannot fly.'\nRules: Max 6 words per line, emotion through CAPS and punctuation, dialogue only.\n\nJulia Donaldson (The Gruffalo):\n'A mouse took a stroll through the deep dark wood. A fox saw the mouse, and the mouse looked good.'\nRules: Perfect AABB rhyme, three encounters before climax, refrain repeated exactly.\n\nAuthor reference from brief:\n{clarify}\n\nCraft research:\n{research}\n\nMatch the SPECIFIC technique of the chosen author. Output: 12 spreads, each with 'Text:' and 'Illustration note:'",
                "model": "o3-pro",
                "role": "author",
            },
            {
                "id": "write",
                "prompt": "Write the final picture book text. ONLY the read-aloud words.\n\nSpread plan:\n{structure}\nAuthor style targets:\n{clarify}\n\nRules:\n- Match the rhythm/style of the referenced authors\n- 100-300 words total\n- If emulating Donaldson: rhyme must scan perfectly\n- If emulating Willems: max 6 words per page\n- If emulating Carle: cumulative 'and then' structure\n- Must work as pure audio (parent reading aloud, no pictures needed to understand)",
                "model": "o3-pro",
                "role": "author",
            },
        ],
        "edges": [
            {"from_node": "clarify", "to_node": "research"},
            {"from_node": "clarify", "to_node": "structure"},
            {"from_node": "research", "to_node": "structure"},
            {"from_node": "structure", "to_node": "write"},
            {"from_node": "clarify", "to_node": "write"},
        ],
        "evals": ["AgeAppropriateness", "StoryArc", "WordCount", "ReadAloudQuality"],
    },
    {
        "id": "cw_early_reader",
        "name": "Early Reader",
        "department": "creative_writing",
        "description": "300-800 words, ages 5-7, studying real early reader masters",
        "nodes": [
            {
                "id": "clarify",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "interviewer",
                "tool": "clarify",
                "tool_config": {
                    "questions": [
                        "How old is the child? What do they already like reading? (This determines which proven styles we'll match.)",
                        "Who is the protagonist? Name, age, 2-3 personality traits, and what makes them relatable to this kid.",
                        "What is the central problem? (lost toy, new school, making a friend, learning something hard)",
                        "What are 3 attempts the character makes to solve the problem? (try-fail-try-fail-succeed pattern)",
                        "What does the character LEARN by the end? How do they grow?",
                        "What tone does this kid respond to? (silly/physical comedy, warm/gentle, adventurous, gross-out funny)",
                    ]
                },
            },
            {
                "id": "research",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {
                    "queries_from_input": True,
                    "query_template": "{input} early reader writing craft techniques leveled reading",
                    "max_results": 3,
                },
            },
            {
                "id": "outline",
                "prompt": "Create a 4-chapter outline studying these REAL examples of what good looks like:\n\nJunie B. Jones (Barbara Park):\n'My name is Junie B. Jones. The B stands for Beatrice. Except I don't like Beatrice. I just like B and that's all. I'm almost six years old.'\nRules: First person, grammar reflects how kids TALK, worries are specific and physical, humor from kid logic.\n\nFrog and Toad (Arnold Lobel):\n'\"What is the matter, Toad?\" \"This is my sad time of day. It is the time when I wait for the mail.\" \"Why?\" \"Because I never get any mail.\"'\nRules: Short declarative sentences, emotion named simply, one friend helps the other, quiet resolution.\n\nElephant & Piggie (Mo Willems):\n'Piggie: I have a ball! Gerald: A ball! Piggie: Let's throw it! Gerald: Yes!'\nRules: ONLY dialogue, emotions 0 to 100 instantly, exclamation points default, repetition = comedy.\n\nAuthor targets from brief:\n{clarify}\n\nCraft research:\n{research}\n\nEach chapter: title, 3-4 beats, emotional state, one moment matching the target author's signature move.",
                "model": "o3-pro",
                "role": "author",
            },
            {
                "id": "draft",
                "prompt": "Write the full early reader from this outline.\n\nOutline:\n{outline}\nAuthor style:\n{clarify}\n\nRules:\n- 300-800 words total\n- If Lobel style: short sentences, gentle humor, friendship at center\n- If Willems style: mostly dialogue, exclamation points, physical reactions\n- If Rylant style: sensory language, 'the sun felt warm on his fur'\n- Flesch-Kincaid grade 1-2\n- Show don't tell emotions",
                "model": "o3-pro",
                "role": "author",
            },
        ],
        "edges": [
            {"from_node": "clarify", "to_node": "research"},
            {"from_node": "clarify", "to_node": "outline"},
            {"from_node": "research", "to_node": "outline"},
            {"from_node": "outline", "to_node": "draft"},
            {"from_node": "clarify", "to_node": "draft"},
        ],
        "evals": [
            "AgeAppropriateness",
            "StoryArc",
            "CharacterConsistency",
            "WordCount",
            "ReadAloudQuality",
        ],
    },
    {
        "id": "cw_chapter_book",
        "name": "Chapter Book Outline",
        "department": "creative_writing",
        "description": "1000-3000 words, ages 7-10, studying real chapter book authors",
        "nodes": [
            {
                "id": "clarify",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "interviewer",
                "tool": "clarify",
                "tool_config": {
                    "questions": [
                        "How old is the reader? What books have they loved? What do they binge? (We'll match proven styles that hook kids like them.)",
                        "What genre? (fantasy, mystery, adventure, realistic fiction, humor) What's a book they couldn't put down?",
                        "Describe the protagonist: name, age, appearance, 3 traits, biggest fear, secret talent, deepest want.",
                        "What is the central conflict? What's at stake if the protagonist fails?",
                        "Who is the antagonist? What makes them interesting (not just 'evil')?",
                        "What is the theme without being preachy? What should the reader FEEL at the end?",
                    ]
                },
            },
            {
                "id": "research",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {
                    "queries_from_input": True,
                    "query_template": "{input} middle grade writing craft chapter book structure",
                    "max_results": 3,
                },
            },
            {
                "id": "world",
                "prompt": "Build the story world studying these REAL examples:\n\nRoald Dahl (Matilda):\n'The Trunchbull had a look about her of an infuriated bull that is about to charge.'\nRules: Adults are grotesque, child is smarter than everyone, invented words, justice is spectacular.\n\nRick Riordan (Percy Jackson):\n'Look, I didn't want to be a half-blood. If you're reading this because you think you might be one, my advice is: close this book right now.'\nRules: First-person snark, direct address, humor under pressure, ADHD as superpower.\n\nJeff Kinney (Wimpy Kid):\n'Let me just say for the record that I think middle school is the dumbest idea ever invented.'\nRules: Diary format, unreliable narrator, social status as life-or-death stakes.\n\nAuthor targets:\n{clarify}\n\nCraft research:\n{research}\n\nCreate: setting (500 words), 3 character profiles with distinct VOICES that match the target author, world rules, tone guide.",
                "model": "o3-pro",
                "role": "worldbuilder",
            },
            {
                "id": "structure",
                "prompt": "Outline 10 chapters using three-act structure.\n\nWorld:\n{world}\nAuthor style:\n{clarify}\n\nPacing reference:\n- Dahl: short chapters, cliffhangers, escalating absurdity\n- DiCamillo: alternating POV, slow build, devastating climax\n- Riordan: action-rest-action, chapter ends mid-sentence\n- Kinney: episodic, each chapter a complete embarrassment\n\nFor each chapter: title, 4-5 beats, emotional arc, chapter-ending hook.",
                "model": "o3-pro",
                "role": "author",
            },
            {
                "id": "sample",
                "prompt": "Write Chapter 1 in full (600-900 words).\n\nOutline:\n{structure}\nWorld:\n{world}\nAuthor voice targets:\n{clarify}\n\nVoice checklist:\n- Dahl: sardonic narrator, invented words, adults are ridiculous\n- DiCamillo: lyrical, short sentences, emotional precision\n- Riordan: first-person snark, action verbs, humor under pressure\n- Cleary: third-person close, kid logic, small stakes feel enormous\n\nThe first paragraph must hook like your target author hooks.",
                "model": "o3-pro",
                "role": "author",
            },
        ],
        "edges": [
            {"from_node": "clarify", "to_node": "research"},
            {"from_node": "clarify", "to_node": "world"},
            {"from_node": "research", "to_node": "world"},
            {"from_node": "world", "to_node": "structure"},
            {"from_node": "clarify", "to_node": "structure"},
            {"from_node": "structure", "to_node": "sample"},
            {"from_node": "world", "to_node": "sample"},
            {"from_node": "clarify", "to_node": "sample"},
        ],
        "evals": ["CharacterConsistency", "StoryArc", "AgeAppropriateness", "WordCount"],
    },
    {
        "id": "cw_bedtime_story",
        "name": "Bedtime Story",
        "department": "creative_writing",
        "description": "200-500 words, calming tone, studying real bedtime story masters",
        "nodes": [
            {
                "id": "clarify",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "interviewer",
                "tool": "clarify",
                "tool_config": {
                    "questions": [
                        "How old is the child? What's their bedtime like right now? (Wired? Scared of dark? Just needs winding down?)",
                        "What creature or character will the child follow to sleep? Describe them as soft, warm, and safe.",
                        "What is the gentle 'adventure' before sleep? (saying goodnight to things, following moonbeams, animals tucking in one by one)",
                        "What sensory details calm this specific child? (warm blanket, rain sounds, parent's heartbeat, soft fur)",
                        "What soothing phrase should repeat like a lullaby? (Must have the same syllable count each time for rhythm.)",
                    ]
                },
            },
            {
                "id": "write",
                "prompt": "Write a bedtime story (200-500 words) studying these REAL examples:\n\nMargaret Wise Brown (Goodnight Moon):\n'Goodnight room. Goodnight moon. Goodnight cow jumping over the moon. Goodnight light and the red balloon. Goodnight bears. Goodnight chairs.'\nRules: List structure, rhythm matches slowing heartbeat, world gets smaller, last line is almost silence.\n\nSam McBratney (Guess How Much I Love You):\n'\"I love you as high as I can reach,\" said Little Nutbrown Hare. \"I love you as high as I can reach,\" said Big Nutbrown Hare.'\nRules: Escalating metaphors, parent matches and exceeds, physical metaphors, child falls asleep, parent gets last word.\n\nBrief:\n{clarify}\n\nRules:\n- Sentences get shorter toward the end (Brown technique)\n- Repeat the soothing phrase 3-4 times at natural breathing pauses\n- Final 3 sentences: 5 words, 4 words, 3 words (decrescendo)\n- NO excitement, NO conflict after the first paragraph\n- End with eyes closing, breathing slowing\n- Must physically slow the reader's breathing like Goodnight Moon does",
                "model": "o3-pro",
                "role": "author",
            },
            {
                "id": "rhythm",
                "prompt": "Review for sleep-inducing rhythm. Compare against Goodnight Moon's pacing:\n\n- Are sentences getting shorter toward the end?\n- Does the repetitive phrase land at natural exhale points?\n- Count syllables in the last 5 sentences — they should decrease\n- Is there any word that's sharp or energizing? Replace with soft alternative\n- Read it aloud in your head — does your breathing slow?\n\nStory:\n{write}",
                "model": "claude-opus-4-6",
                "role": "editor",
            },
        ],
        "edges": [
            {"from_node": "clarify", "to_node": "write"},
            {"from_node": "write", "to_node": "rhythm"},
        ],
        "evals": ["AgeAppropriateness", "ReadAloudQuality", "WordCount"],
    },
    {
        "id": "cw_educational",
        "name": "Educational Story",
        "department": "creative_writing",
        "description": "500-1500 words, teaches a concept, studying real educational story authors",
        "nodes": [
            {
                "id": "clarify",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "interviewer",
                "tool": "clarify",
                "tool_config": {
                    "questions": [
                        "How old is the child? What do they already know about this topic? (We'll pick the right style for their level.)",
                        "What specific concept should they learn? (Not vague — e.g., 'how seeds grow into plants' not 'nature')",
                        "What's the ONE new thing they should understand after reading?",
                        "What character will discover this concept? How does learning it solve their personal problem?",
                        "What are 3 concrete scenes where the concept is demonstrated through action (not explained)?",
                        "What common misconception should the story gently correct?",
                    ]
                },
            },
            {
                "id": "research",
                "prompt": "TOOL_NODE",
                "model": "none",
                "role": "researcher",
                "tool": "web_search",
                "tool_config": {
                    "queries_from_input": True,
                    "query_template": "{input} children educational accurate facts",
                    "max_results": 3,
                },
            },
            {
                "id": "plan",
                "prompt": "Plan the educational story using real author techniques:\n\nBrief:\n{clarify}\nFact research:\n{research}\n\nStructure options (pick based on target author):\n- Cole/Magic School Bus: shrink characters INTO the concept, experience it physically\n- Beaty/Rosie Revere: character fails, fails, fails, then the concept clicks and they succeed\n- Jeffers/Here We Are: zoom out from personal to cosmic, concept as wonder\n- Chin/Grand Canyon: time layers, same place different era, concept revealed through change\n\nThe concept must emerge through CHARACTER ACTION. No character ever says 'did you know...'",
                "model": "o3-pro",
                "role": "educator",
            },
            {
                "id": "write",
                "prompt": "Write the educational story (500-1500 words).\n\nPlan:\n{plan}\nFacts from research:\n{research}\nAuthor style:\n{clarify}\n\nRules:\n- Every fact must be ACCURATE (use the research)\n- Show, don't tell the concept\n- The story works as entertainment FIRST\n- A child who misses the lesson still enjoys the narrative\n- Include one 'wow' moment where reality is more amazing than fiction",
                "model": "o3-pro",
                "role": "author",
            },
        ],
        "edges": [
            {"from_node": "clarify", "to_node": "research"},
            {"from_node": "clarify", "to_node": "plan"},
            {"from_node": "research", "to_node": "plan"},
            {"from_node": "plan", "to_node": "write"},
            {"from_node": "research", "to_node": "write"},
            {"from_node": "clarify", "to_node": "write"},
        ],
        "evals": [
            "AgeAppropriateness",
            "StoryArc",
            "CharacterConsistency",
            "WordCount",
            "ReadAloudQuality",
        ],
    },
]
