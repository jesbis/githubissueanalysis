# GitHub Issue Analysis

Simple Python script to parse and run analytics on a GitHub issue's HTML page source.

Optionally runs Azure Cognitive Services [sentiment analysis](https://docs.microsoft.com/azure/cognitive-services/text-analytics/how-tos/text-analytics-how-to-sentiment-analysis) and [key phrase extraction](https://docs.microsoft.com/azure/cognitive-services/text-analytics/how-tos/text-analytics-how-to-keyword-extraction).

Tested on Python 3.7.3.  
Current to GitHub page source as of June 2 2019.  
Not extensively tested or optimized.  

### Inputs:
- GitHub issue HTML page source
- (optionally) Azure Cognitive Services config file in the form:
```json
       {
           "cognitive_services":
           {
               "endpoint":"<your Azure Cognitive Services endpoint URL>",
               "key":"<your Azure Cogntiive Services key>"
           }
       }
  ```

### Outputs: 
- summary of active participants in an issue including comment count, mention count, and reactions
- (optionally) comment sentiment analysis and key phrases

Can optionally print to:
- std out
- summary text file
- sentiment graph image as .png
- raw .json file

### Dependencies:
```
pip install --upgrade beautifulsoup4
pip install --upgrade tabulate
pip install --upgrade azure-cognitiveservices-language-textanalytics
pip install --upgrade matplotlib
```

### Usage
1.  Save target GitHub issue page as an HTML file (default: `issue.html` in the same directory as the script), e.g. using browser dev tools to get full page source. 
    - If it's a long issue then make sure to **expand the issue to get all comments** (click "Load more" until all comments are loaded)
    - **Do not rely on browser's View Page Source** since that issues a separate page request and therefore misses any comments that have been hidden in long threads, even if you manually clicked "Load More" beforehand.

2. Optionally override defaults in script for:
    - supplying an Azure config file per above (e.g. `azureconfig.json.secret`) to run Azure Cognitive Services analysis
    - `excluded_key_phrases`: list of key phrases to exclude
    - `key_phrase_count`: number of key phrases to output (default 50)
    - `output_filename`: filename(s) to output to current directory
    - `print_summary`, `show_sentiment_plot` switches to control output format

3. Run:
```
> python analyze_github_issue.py
```

### Limitations and notes

- Script just scrapes a GitHub issue's HTML page contents: GitHub could change the structure of its pages at any time and break it.

### Future possibilities

1. Script could be trivially extended to run additional Azure AI analysis, e.g. named entity extraction.
2. Script could be extended to make HTML requests and expand unloaded comments via appropriate AJAX calls rather than running on a pre-saved file.
3. Script could be updated to run as a service, using a GitHub webhook to analyze comments as they come in.
4. Script currently does pessimistic client-side Azure API call throttling: not sure if the Azure SDK does this automatically.
