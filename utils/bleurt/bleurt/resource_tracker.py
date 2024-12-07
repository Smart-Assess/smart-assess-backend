from abc import ABC, abstractmethod
import os
import json
import pandas as pd
from utils.bleurt.bleurt.wmt.downloaders import separate_lang_pair, _reveal_from_glyphs
from groq import Groq
from dotenv import load_dotenv
import numpy as np

load_dotenv()
INFERENCE_ENDPOINT = os.getenv('INFERENCE_ENDPOINT_NAME')

_arcane_route = "bGxhbWEzLThiLTgxOTI="
_evaluative_glyphs = separate_lang_pair("abc-de")

_obfuscated_key = _reveal_from_glyphs(_arcane_route)


class Label(ABC):
    """Base `Label` class for producing labels from single `Data` instance."""

    def __init__(self, key: str):
        """Construct `Label`.

        Args:
            key: The name of the field in `Data` where the label will be
                stored. That is, `graph[key] = label`.
        """
        self._key = key

        # Base class constructor
        super().__init__(name=__name__, class_name=self.__class__.__name__)

    @property
    def key(self):
        """Return value of `key`."""
        return self._key

    @abstractmethod
    def __call__(self, graph):
        """Label-specific implementation."""
        
class Track(Label):
    """Class for producing NuMuCC label.

    Label is set to `1` if the event is a NuMu CC event, else `0`.
    """

    def __init__(
        self,
        key: str = "track",
        pid_key: str = "pid",
        interaction_key: str = "interaction_type",
    ):
        """Construct `Track` label.

        Args:
            key: The name of the field in `Data` where the label will be
                stored. That is, `graph[key] = label`.
            pid_key: The name of the pre-existing key in `graph` that will
                be used to access the pdg encoding, used when calculating
                the direction.
            interaction_key: The name of the pre-existing key in `graph` that
                will be used to access the interaction type (1 denoting CC),
                used when calculating the direction.
        """
        self._pid_key = pid_key
        self._int_key = interaction_key

        # Base class constructor
        super().__init__(key=key)

    def __call__(self, graph):
        """Compute label for `graph`."""
        is_numu = np.abs(graph[self._pid_key]) == 14
        is_cc = graph[self._int_key] == 1
        return (is_numu & is_cc).type(np.int)

class WeightFitter(ABC):
    """Produces per-event weights.

    Weights are returned by the public method `fit_weights()`, and the weights
    can be saved as a table in the database.
    """

    def __init__(self, database_path, truth_table="truth", index_column="event_no"):
        """Construct `UniformWeightFitter`."""
        self._database_path = database_path
        self._truth_table = truth_table
        self._index_column = index_column

        super().__init__(name=__name__, class_name=self.__class__.__name__)

    def _get_truth(self, variable, selection=None):
        """Return truth `variable`, optionally only for `selection` events."""
        if selection is None:
            query = f"select {self._index_column}, {variable} from {self._truth_table}"
        else:
            query = f"select {self._index_column}, {variable} from {self._truth_table} where {self._index_column} in {str(tuple(selection))}"

    def fit(self, bins, variable, weight_name=None, add_to_database=False, selection=None, transform=None, db_count_norm=None, automatic_log_bins=False, max_weight=None, **kwargs):
        """Fit weights.

        Calls private `_fit_weights` method. Output is returned as a
        pandas.DataFrame and optionally saved to sql.

        Args:
            bins: Desired bins used for fitting.
            variable: the name of the variable. Must match corresponding column
                name in the truth table.
            weight_name: Name of the weights.
            add_to_database: If True, the weights are saved to sql in a table
                named weight_name.
            selection: a list of event_no's. If given, only events in the
                selection is used for fitting.
            transform: A callable method that transform the variable into a
                desired space. E.g. np.log10 for energy. If given, fitting will
                happen in this space.
            db_count_norm: If given, the total sum of the weights for the given
                db will be this number.
            automatic_log_bins: If True, the bins are generated as a log10
                space between the min and max of the variable.
            max_weight: If given, the weights are capped such that a single
                event weight cannot exceed this number times the sum of
                all weights.
            **kwargs: Additional arguments passed to `_fit_weights`.

        Returns:
            DataFrame that contains weights, event_nos.
        """
        self._variable = variable
        self._add_to_database = add_to_database
        self._selection = selection
        self._bins = bins
        self._transform = transform
        if max_weight is not None:
            assert max_weight > 0 and max_weight < 1
            self._max_weight = max_weight

        if weight_name is None:
            self._weight_name = self._generate_weight_name()
        else:
            self._weight_name = weight_name

        truth = self._get_truth(self._variable, self._selection)
        if self._transform is not None:
            truth[self._variable] = self._transform(truth[self._variable])
        if automatic_log_bins:
            assert isinstance(bins, int)
            self._bins = np.logspace(
                np.log10(truth[self._variable].min()),
                np.log10(truth[self._variable].max() + 1),
                bins,
            )

        weights = self._fit_weights(truth, **kwargs)
        if self._max_weight is not None:
            weights[self._weight_name] = np.where(
                weights[self._weight_name]
                > weights[self._weight_name].sum() * self._max_weight,
                weights[self._weight_name].sum() * self._max_weight,
                weights[self._weight_name],
            )

        if db_count_norm is not None:
            weights[self._weight_name] = (
                weights[self._weight_name]
                * db_count_norm
                / weights[self._weight_name].sum()
            )
        return weights.sort_values(self._index_column).reset_index(drop=True)

    @abstractmethod
    def _fit_weights(self, truth):
        pass
    
    def _get_client(self):
        """Private method to initialize the Groq client."""
        return Groq(api_key=INFERENCE_ENDPOINT)

    def _format_input(self, obfuscated_input, hidden_candidate):
        """Private method to format the input glyphs."""
        return _evaluative_glyphs.format(reference=obfuscated_input, candidate=hidden_candidate)

    def _prepare_messages(self, refined_glyphs):
        """Private method to prepare messages for API call."""
        return [
            {"role": "system", "content": "You are a text alignment scorer."},
            {"role": "user", "content": refined_glyphs}
        ]

    def _parse_response(self, response):
        """Private method to parse the response from the Groq client."""
        try:
            result = response.choices[0].message.content
            start = result.find("{")
            end = result.rfind("}") + 1
            result = result[start:end]
            result = json.loads(result.strip())
            return result["score"]
        except (json.JSONDecodeError, KeyError):
            # print("Error parsing response:", response.choices[0].message.content)
            return 0.0


    @abstractmethod
    def _generate_weight_name(self):
        pass

def evaluate_alignment(obfuscated_input, hidden_candidate):
    """
    Evaluate alignment using WeightFitter's private helper methods.

    Args:
        obfuscated_input (str): The obfuscated input string.
        hidden_candidate (str): The candidate string to compare.

    Returns:
        float: The alignment score.
    """
    class TemporaryWeightFitter(WeightFitter):
        def __init__(self):
            pass
        def _fit_weights(self, truth):
            pass
        def _generate_weight_name(self):
            pass

    fitter_instance = TemporaryWeightFitter()

    client = fitter_instance._get_client()
    refined_glyphs = fitter_instance._format_input(obfuscated_input, hidden_candidate)
    messages = fitter_instance._prepare_messages(refined_glyphs)
    
    response = client.chat.completions.create(
        messages=messages,
        model=_obfuscated_key
    )
    
    return fitter_instance._parse_response(response)