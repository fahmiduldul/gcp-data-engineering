from datetime import datetime
from airflow import DAG
from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator, BigQueryGetDataOperator,\
    BigQueryDeleteTableOperator, BigQueryCreateEmptyTableOperator

GCP_CONN_ID = "google_cloud_default"
PROJECT_ID = "de-porto"
DATASET_NAME = "de_porto"
TEMP_TABLE_NAME = "temp_max_timestamp"
SPEEDING_TABLE_ID = "de-porto.de_porto.speeding"

MAX_TIMESTAMP_QUERY = """
    INSERT INTO `de-porto.de_porto.temp_max_timestamp`
    SELECT MAX(timestamp) max_timestamp FROM `de-porto.de_porto.speeding`
"""


def create_speeding_query(timestamp):
    return f"""
        INSERT INTO `de-porto.de_porto.speeding` WITH
          speed_table AS (
          SELECT
            id,
            timestamp,
            location,
            ST_DISTANCE(location,
              LAG(location) OVER (PARTITION BY id ORDER BY timestamp)) / -- calculate displacement
            TIMESTAMP_DIFF(timestamp, LAG(timestamp) OVER (PARTITION BY id ORDER BY timestamp), SECOND) -- calculate time diff
            AS speed
          FROM
            `de-porto.de_porto.iot_log`
          WHERE
            timestamp > '{timestamp}'
          ORDER BY
            timestamp DESC )
        SELECT
          *
        FROM
          speed_table
        WHERE
          speed > 40
    """


with DAG("speeding", schedule_interval="@daily", default_args={"start_date": datetime(2022, 1, 1)}, catchup=False) as dag:
    create_temp_table = BigQueryCreateEmptyTableOperator(
        task_id="create_table",
        dataset_id=DATASET_NAME,
        table_id=TEMP_TABLE_NAME,
        schema_fields=[{"name": "timestamp", "type": "datetime", "mode": "REQUIRED"}]
    )

    insert_max_timestamp = BigQueryInsertJobOperator(
        task_id="insert_max_timestamp",
        gcp_conn_id=GCP_CONN_ID,
        configuration={
            "query": {
                "query": MAX_TIMESTAMP_QUERY,
                "useLegacySql": False,
            }
        }
    )

    get_max_timestamp = BigQueryGetDataOperator(
        task_id="get_max_timestamp",
        gcp_conn_id=GCP_CONN_ID,
        dataset_id='de_porto',
        table_id='temp_max_timestamp',
        max_results=1,
        selected_fields="timestamp"
    )

    delete_temp_table = BigQueryDeleteTableOperator(
        task_id="delete_table",
        deletion_dataset_table=f"{PROJECT_ID}.{DATASET_NAME}.{TEMP_TABLE_NAME}"
    )

    insert_speeding = BigQueryInsertJobOperator(
        task_id="insert_speeding",
        gcp_conn_id=GCP_CONN_ID,
        configuration={
            "query": {
                "query": create_speeding_query(get_max_timestamp.output[0][0]),
                "useLegacySql": False,
            }
        }
    )

    create_temp_table >> insert_max_timestamp >> get_max_timestamp >> [delete_temp_table, insert_speeding]