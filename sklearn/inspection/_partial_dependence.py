"""Partial dependence plots for regression and classification models."""

# Authors: Peter Prettenhofer
#          Trevor Stephens
#          Nicolas Hug
# License: BSD 3 clause

from itertools import count

import numpy as np

from ..base import is_classifier, is_regressor
from ..utils import check_matplotlib_support  # noqa
from ..utils import _safe_indexing
from ..utils import _get_column_indices
from ._ice import (
    _get_predictions, _validate_pdp_ice_parameters, _grid_from_X,
    _plot_pdp_ice)


__all__ = ['partial_dependence', 'plot_partial_dependence',
           'PartialDependenceDisplay']


def _partial_dependence_recursion(est, grid, features):
    return est._compute_partial_dependence_recursion(grid, features)


def _partial_dependence_brute(est, grid, features, X, response_method):
    averaged_predictions = []
    predictions = _get_predictions(est, grid, features, X, response_method)
    for prediction in predictions:
        # average over samples
        averaged_predictions.append(np.mean(prediction, axis=0))

    # reshape to (n_targets, n_points) where n_targets is:
    # - 1 for non-multioutput regression and binary classification (shape is
    #   already correct in those cases)
    # - n_tasks for multi-output regression
    # - n_classes for multiclass classification.
    averaged_predictions = np.array(averaged_predictions).T
    if is_regressor(est) and averaged_predictions.ndim == 1:
        # non-multioutput regression, shape is (n_points,)
        averaged_predictions = averaged_predictions.reshape(1, -1)
    elif is_classifier(est) and averaged_predictions.shape[0] == 2:
        # Binary classification, shape is (2, n_points).
        # we output the effect of **positive** class
        averaged_predictions = averaged_predictions[1]
        averaged_predictions = averaged_predictions.reshape(1, -1)

    return averaged_predictions


def partial_dependence(estimator, X, features, response_method='auto',
                       percentiles=(0.05, 0.95), grid_resolution=100,
                       method='auto'):
    """Partial dependence of ``features``.

    Partial dependence of a feature (or a set of features) corresponds to
    the average response of an estimator for each possible value of the
    feature.

    Read more in the :ref:`User Guide <partial_dependence>`.

    Parameters
    ----------
    estimator : BaseEstimator
        A fitted estimator object implementing :term:`predict`,
        :term:`predict_proba`, or :term:`decision_function`.
        Multioutput-multiclass classifiers are not supported.

    X : {array-like or dataframe} of shape (n_samples, n_features)
        ``X`` is used both to generate a grid of values for the
        ``features``, and to compute the averaged predictions when
        method is 'brute'.

    features : array-like of {int, str}
        The feature (e.g. `[0]`) or pair of interacting features
        (e.g. `[(0, 1)]`) for which the partial dependency should be computed.

    response_method : 'auto', 'predict_proba' or 'decision_function', \
            optional (default='auto')
        Specifies whether to use :term:`predict_proba` or
        :term:`decision_function` as the target response. For regressors
        this parameter is ignored and the response is always the output of
        :term:`predict`. By default, :term:`predict_proba` is tried first
        and we revert to :term:`decision_function` if it doesn't exist. If
        ``method`` is 'recursion', the response is always the output of
        :term:`decision_function`.

    percentiles : tuple of float, optional (default=(0.05, 0.95))
        The lower and upper percentile used to create the extreme values
        for the grid. Must be in [0, 1].

    grid_resolution : int, optional (default=100)
        The number of equally spaced points on the grid, for each target
        feature.

    method : str, optional (default='auto')
        The method used to calculate the averaged predictions:

        - 'recursion' is only supported for gradient boosting estimator (namely
          :class:`GradientBoostingClassifier<sklearn.ensemble.GradientBoostingClassifier>`,
          :class:`GradientBoostingRegressor<sklearn.ensemble.GradientBoostingRegressor>`,
          :class:`HistGradientBoostingClassifier<sklearn.ensemble.HistGradientBoostingClassifier>`,
          :class:`HistGradientBoostingRegressor<sklearn.ensemble.HistGradientBoostingRegressor>`)
          but is more efficient in terms of speed.
          With this method, ``X`` is only used to build the
          grid and the partial dependences are computed using the training
          data. This method does not account for the ``init`` predictor of
          the boosting process, which may lead to incorrect values (see
          warning below). With this method, the target response of a
          classifier is always the decision function, not the predicted
          probabilities.

        - 'brute' is supported for any estimator, but is more
          computationally intensive.

        - 'auto':

          - 'recursion' is used for
            :class:`GradientBoostingClassifier<sklearn.ensemble.GradientBoostingClassifier>`
            and
            :class:`GradientBoostingRegressor<sklearn.ensemble.GradientBoostingRegressor>`
            if ``init=None``, and for
            :class:`HistGradientBoostingClassifier<sklearn.ensemble.HistGradientBoostingClassifier>`
            and
            :class:`HistGradientBoostingRegressor<sklearn.ensemble.HistGradientBoostingRegressor>`.
          - 'brute' is used for all other estimators.

    Returns
    -------
    averaged_predictions : ndarray, \
            shape (n_outputs, len(values[0]), len(values[1]), ...)
        The predictions for all the points in the grid, averaged over all
        samples in X (or over the training data if ``method`` is
        'recursion'). ``n_outputs`` corresponds to the number of classes in
        a multi-class setting, or to the number of tasks for multi-output
        regression. For classical regression and binary classification
        ``n_outputs==1``. ``n_values_feature_j`` corresponds to the size
        ``values[j]``.

    values : seq of 1d ndarrays
        The values with which the grid has been created. The generated grid
        is a cartesian product of the arrays in ``values``. ``len(values) ==
        len(features)``. The size of each array ``values[j]`` is either
        ``grid_resolution``, or the number of unique values in ``X[:, j]``,
        whichever is smaller.

    Examples
    --------
    >>> X = [[0, 0, 2], [1, 0, 0]]
    >>> y = [0, 1]
    >>> from sklearn.ensemble import GradientBoostingClassifier
    >>> gb = GradientBoostingClassifier(random_state=0).fit(X, y)
    >>> partial_dependence(gb, features=[0], X=X, percentiles=(0, 1),
    ...                    grid_resolution=2) # doctest: +SKIP
    (array([[-4.52...,  4.52...]]), [array([ 0.,  1.])])

    See also
    --------
    sklearn.inspection.plot_partial_dependence: Plot partial dependence

    Warnings
    --------
    The 'recursion' method only works for gradient boosting estimators, and
    unlike the 'brute' method, it does not account for the ``init``
    predictor of the boosting process. In practice this will produce the
    same values as 'brute' up to a constant offset in the target response,
    provided that ``init`` is a consant estimator (which is the default).
    However, as soon as ``init`` is not a constant estimator, the partial
    dependence values are incorrect for 'recursion'. This is not relevant for
    :class:`HistGradientBoostingClassifier
    <sklearn.ensemble.HistGradientBoostingClassifier>` and
    :class:`HistGradientBoostingRegressor
    <sklearn.ensemble.HistGradientBoostingRegressor>`, which do not have an
    ``init`` parameter.
    """
    X, response_method, method = _validate_pdp_ice_parameters(estimator, X,
                                                              features,
                                                              response_method,
                                                              method)

    features_indices = np.asarray(
        _get_column_indices(X, features), dtype=np.int32, order='C'
    ).ravel()

    grid, values = _grid_from_X(
        _safe_indexing(X, features_indices, axis=1), percentiles,
        grid_resolution
    )

    if method == 'brute':
        averaged_predictions = _partial_dependence_brute(
            estimator, grid, features_indices, X, response_method
        )
    else:
        averaged_predictions = _partial_dependence_recursion(
            estimator, grid, features_indices
        )

    # reshape averaged_predictions to
    # (n_outputs, n_values_feature_0, n_values_feature_1, ...)
    averaged_predictions = averaged_predictions.reshape(
        -1, *[val.shape[0] for val in values])

    return averaged_predictions, values


def plot_partial_dependence(estimator, X, features, feature_names=None,
                            target=None, response_method='auto', n_cols=3,
                            grid_resolution=100, percentiles=(0.05, 0.95),
                            method='auto', n_jobs=None, verbose=0, fig=None,
                            line_kw=None, contour_kw=None, ax=None):
    """Partial dependence plots.

    The ``len(features)`` plots are arranged in a grid with ``n_cols``
    columns. Two-way partial dependence plots are plotted as contour plots. The
    deciles of the feature values will be shown with tick marks on the x-axes
    for one-way plots, and on both axes for two-way plots.

    .. note::

        :func:`plot_partial_dependence` does not support using the same axes
        with multiple calls. To plot the the partial dependence for multiple
        estimators, please pass the axes created by the first call to the
        second call::

          >>> from sklearn.inspection import plot_partial_dependence
          >>> from sklearn.datasets import make_friedman1
          >>> from sklearn.linear_model import LinearRegression
          >>> X, y = make_friedman1()
          >>> est = LinearRegression().fit(X, y)
          >>> disp1 = plot_partial_dependence(est, X)  # doctest: +SKIP
          >>> disp2 = plot_partial_dependence(est, X,
          ...                                 ax=disp1.axes_)  # doctest: +SKIP

    Read more in the :ref:`User Guide <partial_dependence>`.

    Parameters
    ----------
    estimator : BaseEstimator
        A fitted estimator object implementing :term:`predict`,
        :term:`predict_proba`, or :term:`decision_function`.
        Multioutput-multiclass classifiers are not supported.

    X : {array-like or dataframe} of shape (n_samples, n_features)
        The data to use to build the grid of values on which the dependence
        will be evaluated. This is usually the training data.

    features : list of {int, str, pair of int, pair of str}
        The target features for which to create the PDPs.
        If features[i] is an int or a string, a one-way PDP is created; if
        features[i] is a tuple, a two-way PDP is created. Each tuple must be
        of size 2.
        if any entry is a string, then it must be in ``feature_names``.

    feature_names : array-like of shape (n_features,), dtype=str, default=None
        Name of each feature; feature_names[i] holds the name of the feature
        with index i.
        By default, the name of the feature corresponds to their numerical
        index for NumPy array and their column name for pandas dataframe.

    target : int, optional (default=None)
        - In a multiclass setting, specifies the class for which the PDPs
          should be computed. Note that for binary classification, the
          positive class (index 1) is always used.
        - In a multioutput setting, specifies the task for which the PDPs
          should be computed.

        Ignored in binary classification or classical regression settings.

    response_method : 'auto', 'predict_proba' or 'decision_function', \
            optional (default='auto')
        Specifies whether to use :term:`predict_proba` or
        :term:`decision_function` as the target response. For regressors
        this parameter is ignored and the response is always the output of
        :term:`predict`. By default, :term:`predict_proba` is tried first
        and we revert to :term:`decision_function` if it doesn't exist. If
        ``method`` is 'recursion', the response is always the output of
        :term:`decision_function`.

    n_cols : int, optional (default=3)
        The maximum number of columns in the grid plot. Only active when `ax`
        is a single axis or `None`.

    grid_resolution : int, optional (default=100)
        The number of equally spaced points on the axes of the plots, for each
        target feature.

    percentiles : tuple of float, optional (default=(0.05, 0.95))
        The lower and upper percentile used to create the extreme values
        for the PDP axes. Must be in [0, 1].

    method : str, optional (default='auto')
        The method to use to calculate the partial dependence predictions:

        - 'recursion' is only supported for gradient boosting estimator (namely
          :class:`GradientBoostingClassifier<sklearn.ensemble.GradientBoostingClassifier>`,
          :class:`GradientBoostingRegressor<sklearn.ensemble.GradientBoostingRegressor>`,
          :class:`HistGradientBoostingClassifier<sklearn.ensemble.HistGradientBoostingClassifier>`,
          :class:`HistGradientBoostingRegressor<sklearn.ensemble.HistGradientBoostingRegressor>`)
          but is more efficient in terms of speed.
          With this method, ``X`` is optional and is only used to build the
          grid and the partial dependences are computed using the training
          data. This method does not account for the ``init`` predictor of
          the boosting process, which may lead to incorrect values (see
          warning below. With this method, the target response of a
          classifier is always the decision function, not the predicted
          probabilities.

        - 'brute' is supported for any estimator, but is more
          computationally intensive.

        - 'auto':
          - 'recursion' is used for estimators that supports it.
          - 'brute' is used for all other estimators.

    n_jobs : int, optional (default=None)
        The number of CPUs to use to compute the partial dependences.
        ``None`` means 1 unless in a :obj:`joblib.parallel_backend` context.
        ``-1`` means using all processors. See :term:`Glossary <n_jobs>`
        for more details.

    verbose : int, optional (default=0)
        Verbose output during PD computations.

    fig : Matplotlib figure object, optional (default=None)
        A figure object onto which the plots will be drawn, after the figure
        has been cleared. By default, a new one is created.

        .. deprecated:: 0.22
           ``fig`` will be removed in 0.24.

    line_kw : dict, optional
        Dict with keywords passed to the ``matplotlib.pyplot.plot`` call.
        For one-way partial dependence plots.

    contour_kw : dict, optional
        Dict with keywords passed to the ``matplotlib.pyplot.contourf`` call.
        For two-way partial dependence plots.

    ax : Matplotlib axes or array-like of Matplotlib axes, default=None
        - If a single axis is passed in, it is treated as a bounding axes
            and a grid of partial dependence plots will be drawn within
            these bounds. The `n_cols` parameter controls the number of
            columns in the grid.
        - If an array-like of axes are passed in, the partial dependence
            plots will be drawn directly into these axes.
        - If `None`, a figure and a bounding axes is created and treated
            as the single axes case.

        .. versionadded:: 0.22

    Returns
    -------
    display: :class:`~sklearn.inspection.PartialDependenceDisplay`

    Examples
    --------
    >>> from sklearn.datasets import make_friedman1
    >>> from sklearn.ensemble import GradientBoostingRegressor
    >>> X, y = make_friedman1()
    >>> clf = GradientBoostingRegressor(n_estimators=10).fit(X, y)
    >>> plot_partial_dependence(clf, X, [0, (0, 1)]) #doctest: +SKIP

    See also
    --------
    sklearn.inspection.partial_dependence: Return raw partial
      dependence values

    Warnings
    --------
    The 'recursion' method only works for gradient boosting estimators, and
    unlike the 'brute' method, it does not account for the ``init``
    predictor of the boosting process. In practice this will produce the
    same values as 'brute' up to a constant offset in the target response,
    provided that ``init`` is a consant estimator (which is the default).
    However, as soon as ``init`` is not a constant estimator, the partial
    dependence values are incorrect for 'recursion'. This is not relevant for
    :class:`HistGradientBoostingClassifier
    <sklearn.ensemble.HistGradientBoostingClassifier>` and
    :class:`HistGradientBoostingRegressor
    <sklearn.ensemble.HistGradientBoostingRegressor>`, which do not have an
    ``init`` parameter.
    """
    return _plot_pdp_ice(estimator, X, features, partial_dependence,
                         PartialDependenceDisplay, feature_names=feature_names,
                         target=target, response_method=response_method,
                         n_cols=n_cols, grid_resolution=grid_resolution,
                         percentiles=percentiles, method=method,
                         n_jobs=n_jobs, verbose=verbose, fig=fig,
                         line_kw=line_kw, contour_kw=contour_kw, ax=ax)


class PartialDependenceDisplay:
    """Partial Dependence Plot (PDP) visualization.

    It is recommended to use
    :func:`~sklearn.inspection.plot_partial_dependence` to create a
    :class:`~sklearn.inspection.PartialDependenceDisplay`. All parameters are
    stored as attributes.

    Read more in
    :ref:`sphx_glr_auto_examples_plot_partial_dependence_visualization_api.py`
    and the :ref:`User Guide <visualizations>`.

        .. versionadded:: 0.22

    Parameters
    ----------
    pd_results : list of (ndarray, ndarray)
        Results of :func:`~sklearn.inspection.partial_dependence` for
        ``features``. Each tuple corresponds to a (averaged_predictions, grid).

    features : list of (int,) or list of (int, int)
        Indices of features for a given plot. A tuple of one integer will plot
        a partial dependence curve of one feature. A tuple of two integers will
        plot a two-way partial dependence curve as a contour plot.

    feature_names : list of str
        Feature names corresponding to the indices in ``features``.

    target_idx : int

        - In a multiclass setting, specifies the class for which the PDPs
          should be computed. Note that for binary classification, the
          positive class (index 1) is always used.
        - In a multioutput setting, specifies the task for which the PDPs
          should be computed.

        Ignored in binary classification or classical regression settings.

    pdp_lim : dict
        Global min and max average predictions, such that all plots will have
        the same scale and y limits. `pdp_lim[1]` is the global min and max for
        single partial dependence curves. `pdp_lim[2]` is the global min and
        max for two-way partial dependence curves.

    deciles : dict
        Deciles for feature indices in ``features``.

    Attributes
    ----------
    bounding_ax_ : matplotlib Axes or None
        If `ax` is an axes or None, the `bounding_ax_` is the axes where the
        grid of partial dependence plots are drawn. If `ax` is a list of axes
        or a numpy array of axes, `bounding_ax_` is None.

    axes_ : ndarray of matplotlib Axes
        If `ax` is an axes or None, `axes_[i, j]` is the axes on the i-th row
        and j-th column. If `ax` is a list of axes, `axes_[i]` is the i-th item
        in `ax`. Elements that are None corresponds to a nonexisting axes in
        that position.

    lines_ : ndarray of matplotlib Artists
        If `ax` is an axes or None, `line_[i, j]` is the partial dependence
        curve on the i-th row and j-th column. If `ax` is a list of axes,
        `lines_[i]` is the partial dependence curve corresponding to the i-th
        item in `ax`. Elements that are None corresponds to a nonexisting axes
        or an axes that does not include a line plot.

    contours_ : ndarray of matplotlib Artists
        If `ax` is an axes or None, `contours_[i, j]` is the partial dependence
        plot on the i-th row and j-th column. If `ax` is a list of axes,
        `contours_[i]` is the partial dependence plot corresponding to the i-th
        item in `ax`. Elements that are None corresponds to a nonexisting axes
        or an axes that does not include a contour plot.

    figure_ : matplotlib Figure
        Figure containing partial dependence plots.

    """
    def __init__(self, pd_results, features, feature_names, target_idx,
                 pdp_lim, deciles):
        self.pd_results = pd_results
        self.features = features
        self.feature_names = feature_names
        self.target_idx = target_idx
        self.pdp_lim = pdp_lim
        self.deciles = deciles

    def plot(self, ax=None, n_cols=3, line_kw=None, contour_kw=None):
        """Plot partial dependence plots.

        Parameters
        ----------
        ax : Matplotlib axes or array-like of Matplotlib axes, default=None
            - If a single axis is passed in, it is treated as a bounding axes
                and a grid of partial dependence plots will be drawn within
                these bounds. The `n_cols` parameter controls the number of
                columns in the grid.
            - If an array-like of axes are passed in, the partial dependence
                plots will be drawn directly into these axes.
            - If `None`, a figure and a bounding axes is created and treated
                as the single axes case.

        n_cols : int, default=3
            The maximum number of columns in the grid plot. Only active when
            `ax` is a single axes or `None`.

        line_kw : dict, default=None
            Dict with keywords passed to the `matplotlib.pyplot.plot` call.
            For one-way partial dependence plots.

        contour_kw : dict, default=None
            Dict with keywords passed to the `matplotlib.pyplot.contourf`
            call for two-way partial dependence plots.

        Returns
        -------
        display: :class:`~sklearn.inspection.PartialDependenceDisplay`
        """

        check_matplotlib_support("plot_partial_dependence")
        import matplotlib.pyplot as plt  # noqa
        from matplotlib import transforms  # noqa
        from matplotlib.ticker import MaxNLocator  # noqa
        from matplotlib.ticker import ScalarFormatter  # noqa
        from matplotlib.gridspec import GridSpecFromSubplotSpec  # noqa

        if line_kw is None:
            line_kw = {}
        if contour_kw is None:
            contour_kw = {}

        if ax is None:
            _, ax = plt.subplots()

        default_contour_kws = {"alpha": 0.75}
        contour_kw = {**default_contour_kws, **contour_kw}

        n_features = len(self.features)

        if isinstance(ax, plt.Axes):
            # If ax was set off, it has most likely been set to off
            # by a previous call to plot.
            if not ax.axison:
                raise ValueError("The ax was already used in another plot "
                                 "function, please set ax=display.axes_ "
                                 "instead")

            ax.set_axis_off()
            self.bounding_ax_ = ax
            self.figure_ = ax.figure

            n_cols = min(n_cols, n_features)
            n_rows = int(np.ceil(n_features / float(n_cols)))

            self.axes_ = np.empty((n_rows, n_cols), dtype=np.object)
            self.lines_ = np.empty((n_rows, n_cols), dtype=np.object)
            self.contours_ = np.empty((n_rows, n_cols), dtype=np.object)

            axes_ravel = self.axes_.ravel()

            gs = GridSpecFromSubplotSpec(n_rows, n_cols,
                                         subplot_spec=ax.get_subplotspec())
            for i, spec in zip(range(n_features), gs):
                axes_ravel[i] = self.figure_.add_subplot(spec)

        else:  # array-like
            ax = np.asarray(ax, dtype=object)
            if ax.size != n_features:
                raise ValueError("Expected ax to have {} axes, got {}"
                                 .format(n_features, ax.size))

            if ax.ndim == 2:
                n_cols = ax.shape[1]
            else:
                n_cols = None

            self.bounding_ax_ = None
            self.figure_ = ax.ravel()[0].figure
            self.axes_ = ax
            self.lines_ = np.empty_like(ax, dtype=np.object)
            self.contours_ = np.empty_like(ax, dtype=np.object)

        # create contour levels for two-way plots
        if 2 in self.pdp_lim:
            Z_level = np.linspace(*self.pdp_lim[2], num=8)
        lines_ravel = self.lines_.ravel(order='C')
        contours_ravel = self.contours_.ravel(order='C')

        for i, axi, fx, (avg_preds, values) in zip(count(),
                                                   self.axes_.ravel(),
                                                   self.features,
                                                   self.pd_results):
            if len(values) == 1:
                lines_ravel[i] = axi.plot(values[0],
                                          avg_preds[self.target_idx].ravel(),
                                          **line_kw)[0]
            else:
                # contour plot
                XX, YY = np.meshgrid(values[0], values[1])
                Z = avg_preds[self.target_idx].T
                CS = axi.contour(XX, YY, Z, levels=Z_level, linewidths=0.5,
                                 colors='k')
                contours_ravel[i] = axi.contourf(XX, YY, Z, levels=Z_level,
                                                 vmax=Z_level[-1],
                                                 vmin=Z_level[0],
                                                 **contour_kw)
                axi.clabel(CS, fmt='%2.2f', colors='k', fontsize=10,
                           inline=True)

            trans = transforms.blended_transform_factory(axi.transData,
                                                         axi.transAxes)
            ylim = axi.get_ylim()
            axi.vlines(self.deciles[fx[0]], 0, 0.05, transform=trans,
                       color='k')
            axi.set_ylim(ylim)

            # Set xlabel if it is not already set
            if not axi.get_xlabel():
                axi.set_xlabel(self.feature_names[fx[0]])

            if len(values) == 1:
                if n_cols is None or i % n_cols == 0:
                    axi.set_ylabel('Partial dependence')
                else:
                    axi.set_yticklabels([])
                axi.set_ylim(self.pdp_lim[1])
            else:
                # contour plot
                trans = transforms.blended_transform_factory(axi.transAxes,
                                                             axi.transData)
                xlim = axi.get_xlim()
                axi.hlines(self.deciles[fx[1]], 0, 0.05, transform=trans,
                           color='k')
                # hline erases xlim
                axi.set_ylabel(self.feature_names[fx[1]])
                axi.set_xlim(xlim)
        return self
