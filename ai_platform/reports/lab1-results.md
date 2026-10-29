Measure	Baseline	Rerank k=5	Note
recall@1 / @5 / @8 (hybrid)	0.50 / 0.80 / 1.00	0.90 / 1.00 / 1.00	20 labelled questions
Eval score	98.0 (re-run 97.0)	96.0	rag 94.4, agent 100
Eval cost	$1.71	$1.54	rerank adds $0.03 per 50 q
Rerank call	n/a	$0.0006, ~1 s	Haiku
Partials	0	4, all multi-chunk “why” questions	depth 6/7/8 didn’t fix; variance
Decision		rerank off by default, k=8; flag kept	
