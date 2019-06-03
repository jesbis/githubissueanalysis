# Analyzes a GitHub issue.
#
# Inputs:
#   - GitHub issue HTML page source
#   - (optionally) Azure Cognitive Services config file in the form:
#       {
#           "cognitive_services":
#           {
#               "endpoint":"<your Azure Cognitive Services endpoint URL>",
#               "key":"<your Azure Cogntiive Services key>"
#           }
#       }
#
# Outputs: (optionally to terminal, summary text file, sentiment graph image, and raw .json data)
#   - summary of active participants in an issue including comment count, mention count, and reactions
#   - (optionally) comment sentiment analysis and key phrases
#
# Dependencies:
#   pip install --upgrade beautifulsoup4
#   pip install --upgrade tabulate
#   pip install --upgrade azure-cognitiveservices-language-textanalytics
#   pip install --upgrade matplotlib

import datetime
import json
import os
import re
from collections import Counter
from collections import OrderedDict
from itertools import groupby
from statistics import mean
from time import sleep
from typing import Dict, List

import matplotlib.pyplot as plt
from azure.cognitiveservices.language.textanalytics import TextAnalyticsClient
from bs4 import BeautifulSoup
from tabulate import tabulate
from msrest.authentication import CognitiveServicesCredentials

class GitHubCommentData:
    """Data about a GitHub comment in an issue."""
    def __init__(self, comment_text: str, comment_reactions, sentiment_score: float, key_phrases):
        self.comment_text: str = comment_text
        self.comment_reactions = comment_reactions
        self.sentiment_score: float = sentiment_score
        self.key_phrases = key_phrases


    def get_serializable(self) -> Dict:
        """Returns a serialization-friendly version of the GitHubCommentData instance."""
        result = {}
        result["comment_text"] = self.comment_text
        result["comment_reactions"] = self.comment_reactions
        result["sentiment_score"] = self.sentiment_score
        result["key_phrases"] = self.key_phrases
        return result


    def __str__(self):
        return "GitHub comment: %s" % (self.comment_text[:50])


    def __repr__(self):
        return "GitHub comment: %s" % (self.comment_text[:50])


class GitHubUserData:
    """Stores info about a GitHub user participating in an issue."""
    def __init__(self, is_issue_author: bool, is_member: bool):
        self.is_issue_author = is_issue_author
        self.is_member = is_member
        self.comment_count = 0
        self.mention_count = 0
        self.comment_details = []


    def get_key_phrases_counter(self, excluded_key_phrases: List[str]) -> Counter:
        """Returns a Counter instance containing all key phrases from all of the user's comments."""
        # Get list of key_phrase lists, dropping empty lists
        result = [comment_detail.key_phrases for comment_detail in self.comment_details if comment_detail.key_phrases]
        # Flatten and count list
        return Counter([key_phrase for key_phrase_list in result for key_phrase in key_phrase_list if key_phrase not in excluded_key_phrases])


    def get_reactions_summary(self, use_emojis: bool = False):
        """Returns a sorted list of summed reaction counts for all of the user's comments."""
        # Get list of reactions lists, dropping empty lists
        result = [comment_detail.comment_reactions for comment_detail in self.comment_details if comment_detail.comment_reactions]
        # Flatten list and sort so that it can be summed using groupby
        result = sorted([reaction for reaction_list in result for reaction in reaction_list])
        # Sum flattened list
        result = [(k, sum(count for _, count in v)) for k, v in groupby(result, lambda x : x[0])]
        # Sort flattened summed list by descending number of reactions
        result = sorted(result, key = lambda x : x[1], reverse = True)

        # Not all terminals support rendering emojis, so optionally substitute
        if use_emojis:
            reaction_emojis = {}
            reaction_emojis["THUMBS_UP"] = "👍"
            reaction_emojis["THUMBS_DOWN"] = "👎"
            reaction_emojis["HEART"] = "❤️"
            reaction_emojis["LAUGH"] = "😄️"
            reaction_emojis["HOORAY"] = "🎉"
            reaction_emojis["CONFUSED"] = "😕"
            reaction_emojis["ROCKET"] = "🚀"
            reaction_emojis["EYES"] = "👀"
            result = [(reaction[0].replace(reaction[0], reaction_emojis[reaction[0]]), reaction[1]) for reaction in result]

        return result

    def get_average_sentiment_score(self) -> float:
        """Returns an average sentiment score for all of the user's comments, or -1 if the user did not comment."""
        averages = [comment_detail.sentiment_score for comment_detail in self.comment_details]
        return mean(averages) if averages else -1


    def get_serializable(self) -> Dict:
        """Returns a serialization-friendly version of the GitHubUserData instance."""
        result = {}
        result["is_issue_author"] = self.is_issue_author
        result["is_member"] = self.is_member
        result["comment_count"] = self.comment_count
        result["mention_count"] = self.mention_count
        result["comment_details"] = [comment.get_serializable() for comment in self.comment_details]
        return result

    def __str__(self):
        return "GitHub user: is_issue_author:%s; is_member:%s; comment_count:%s, mention_count:%s, comment_details.count:%s" % (str(self.is_issue_author), str(self.is_member), self.comment_count, self.mention_count, len(self.comment_details))


    def __repr__(self):
        return "GitHubUserData: is_issue_author:%s; is_member:%s; comment_count:%s, mention_count:%s, comment_details.count:%s" % (str(self.is_issue_author), str(self.is_member), self.comment_count, self.mention_count, len(self.comment_details))


class GitHubIssueData:
    """Extracts and stores info about a GitHub issue from a given HTML file.

       If analytics_config_filename is supplied then will also attempt to run Azure Cognitive Services text analytics, otherwise will contain default sentiment and key phrase data.
    """
    def __init__(self, file_name: str, analytics_config_filename: str = None):
        self.sentiments: List[float] = []
        self._analytics_config_filename:str = analytics_config_filename
        with open(file_name, 'r', encoding="utf8") as file:
            self._soup: BeautifulSoup = BeautifulSoup(file.read(), "html.parser")
        self.title: str = self._soup.title.string
        self._comments = self._soup("div", class_="unminimized-comment")
        self._original_post = self._comments.pop(0)  # Remove original post from comments list
        self.comment_count: int = len(self._comments) # Get comment count after popping original post
        self.users = self._populate_user_data()


    def _populate_user_data(self):
        users = {}

        is_member_regex = re.compile(r"^(This user is|You are) a member of the .* organization\.$")
        reaction_count_regex = re.compile(r"\D*")

        if self._analytics_config_filename:
            with open(self._analytics_config_filename, "r") as file:
                azure_config = json.load(file)
            text_analytics = TextAnalyticsClient(endpoint = azure_config["cognitive_services"]["endpoint"], credentials = CognitiveServicesCredentials(azure_config["cognitive_services"]["key"]))

        for comment in self._comments:
            user = comment.find("a", class_="author").get_text()

            # Add user to list if not already present
            if user not in users:
                users[user] = GitHubUserData(
                    is_issue_author = True if comment.find("span",attrs={"aria-label": "You are the author of this issue."}) else False,
                    is_member = True if comment.find("span",attrs={"aria-label": is_member_regex}) else False,
                )

            user_data = users[user]

            # Increment comment count for user
            user_data.comment_count += 1

            comment_text = comment.find("textarea",attrs={"name": "issue[body]"}).get_text()

            # Default to neutral sentiment if Azure analytics aren't run
            sentiment_score = 0.5
            # Default to empty key phrases if Azure analytics aren't run
            key_phrases = []

            # Run Azure analytics if a config file was supplied
            if self._analytics_config_filename:
                sleep(0.05) # Throttle Azure API requests - not sure if SDK also does throttling
                # Create shared request payload
                comment_text_analysis_request_payload = [
                    {
                        "id": "1",
                        "language": "en", # Assume en
                        "text": comment_text[:5000] # Truncate to ensure under 5120 total request character limit
                    }
                ]
                # Do sentiment analysis
                sentiment_response = text_analytics.sentiment(documents = comment_text_analysis_request_payload)
                sentiment_score = sentiment_response.documents[0].score
                # Do key phrase extraction
                key_phrase_response = text_analytics.key_phrases(documents = comment_text_analysis_request_payload)
                key_phrases = key_phrase_response.documents[0].key_phrases

            # Get list of comment reactions, if any
            comment_reactions_source = comment.find("div",class_="has-reactions")
            comment_reactions = []
            if comment_reactions_source:
                for button in comment_reactions_source("button"):
                    reaction_count = re.sub(reaction_count_regex, "", button.get_text())
                    if reaction_count:
                        comment_reactions.append((button["value"].split(" ", 1)[0], int(reaction_count)))

            # Add comment details
            #user_data.comment_details.append((comment_text, comment_reactions, sentiment_score, key_phrases))
            user_data.comment_details.append(GitHubCommentData(comment_text, comment_reactions, sentiment_score, key_phrases))

            # Keep chronological list of sentiments
            self.sentiments.append(sentiment_score)

        # Get count of mentions and update user collection
        # We do this after adding comment data for users to ensure that organization membership status is populated where available
        mentioned_counts = {user:int(doubled_count / 2) for (user, doubled_count) in Counter(user.get_text()[1:] for user in self._soup("a", class_="user-mention")).items()} # trim leading '@' from user names and divide counts by 2 because GitHub pages keep 2 copies of each
        for user, mention_count in mentioned_counts.items():
            # Don't readily know if users who were mentioned but never commented are members or not, so just assume not
            users.setdefault(user, GitHubUserData(False, False)).mention_count = mention_count

        return users


    def get_participant_count_summary(self):
        return self._soup.find("div",class_="participation").div.string.strip()


    def get_tabulated_top_key_phrases(self, key_phrase_count: int = 20, exclude_user_names: bool = True, excluded_key_phrases: List[str] = []) -> Counter:
        """Returns a table of the top n key phrases found in all issue comments.

           Excludes user names of issue commenters if exclude_user_names is True.

           Excludes any key phrases in excluded_key_phrases.
        """
        excluded_phrases = excluded_key_phrases + list(self.users.keys()) if exclude_user_names else []

        total_count = Counter()
        for user in self.users.values():
            total_count += user.get_key_phrases_counter(excluded_key_phrases = excluded_phrases)

        return tabulate(
            total_count.most_common(key_phrase_count),
            headers=["Key phrase", "Frequency"])


    def get_tabulated_user_interaction_data(self, use_emojis: bool = False):
        """Returns a sorted table of interesting user interaction data from the issue's comments."""
        # Sort users
        sorted_users = OrderedDict(sorted(
            self.users.items(),
            key=lambda u: (u[1].comment_count, u[1].mention_count, u[0]),
            reverse=True))

        # Return tabulated list of interesting user info
        return tabulate(((
            "#" if val.is_issue_author else "",
            "*" if val.is_member else "",
            key, # Name
            val.comment_count,
            val.mention_count,
            val.get_average_sentiment_score(),
            val.get_reactions_summary(use_emojis)) for (key,val) in sorted_users.items()),
            headers=["", "", "User", "Comment count", "Times @mentioned", "Avg Sentiment", "Reactions"])


    def get_serializable(self) -> Dict:
        """Returns a serialization-friendly version of the GitHubIssueData instance."""
        result = {}
        result["title"] = self.title
        result["comment_count"] = self.comment_count
        result["sentiments"] = self.sentiments
        result["users"] = {name:user_data.get_serializable() for name, user_data in self.users.items()}
        return result


    def __str__(self):
        return "GitHub issue: %s" % (self.title)


    def __repr__(self):
        return "GitHubIssue: %s" % (self.title)


def analyze_github_comments(issue: GitHubIssueData, key_phrase_count: int = 50, excluded_key_phrases : List[str] = [], print_summary: bool = True, show_sentiment_plot: bool = True, output_filename: str = None):
    """Prints analysis of a GitHub issue and comments."""

    output_sections = [
        "Summary of GitHub issue: " + issue.title,
        "Analyzed: %s comments from %s" % (str(issue.comment_count), issue.get_participant_count_summary()),
        "User summary from all comments:",
        issue.get_tabulated_user_interaction_data(),
        "Top %s key phrases from all comments:" % (str(key_phrase_count)),
        issue.get_tabulated_top_key_phrases(key_phrase_count, excluded_key_phrases = excluded_key_phrases),
        "Excludes keyphrases: %s" % excluded_key_phrases,
    ]

    if print_summary:
        print("\n\n".join(output_sections))

    # Plot comment sentiments over time
    plt.plot(issue.sentiments)
    plt.title("Sentiment over time")
    plt.ylabel("Sentiment")
    plt.xlabel("Comment")
    sentiment_figure = plt.gcf()

    if output_filename:
        # Write analysis summary to txt file
        with open(output_filename, "w", encoding="utf8") as file:
            file.write("\n".join(output_sections))
            print("Saved detailed results to %s" % (os.path.abspath(output_filename)))
        # Write sentiment plot to png file
        plot_filename = output_filename + "-sentiment_plot.png"
        sentiment_figure.savefig(plot_filename)
        print("Saved sentiment plot to %s" % (os.path.abspath(plot_filename)))
        # Write raw data to json file
        raw_json_filename = output_filename + "-raw_output.json"
        with open(raw_json_filename, "w", encoding="utf8") as file:
            json.dump(issue.get_serializable(), file, indent = 2)
            print("Saved raw json output to %s" % (os.path.abspath(raw_json_filename)))

    if show_sentiment_plot:
        plt.show()

# Run without Azure text analytics
issue = GitHubIssueData("issue.html")
# Run with Azure text analytics
#issue = GitHubIssueData("issue.html", analytics_config_filename = "azureconfig.json.secret")

analyze_github_comments(
    issue,
    excluded_key_phrases = [],
    print_summary = True,
    show_sentiment_plot = True,
    output_filename = "GitHub issue analysis %s.txt" % (datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    )


