header_template = """
                <!DOCTYPE html>
                <html>
                <head>
                <style>
                    #result {
                    font-family: "Trebuchet MS", Arial, Helvetica, sans-serif;
                    border-collapse: collapse;
                    width: 80%;
                    }
                    #result td, #result th {
                    border: 1px solid #ddd;
                    padding: 8px;
                    }
                    #result tr:nth-child(even){background-color: #f2f2f2;}
                    #result tr:hover {background-color: #ddd;}
                    #result th {
                    padding-top: 12px;
                    padding-bottom: 12px;
                    text-align: left;
                    background-color: #4CAF50;
                    color: white;
                    }
                </style>
                </head>
                <body>
                <table id="result">
                    <tr>
                        <th>Test Suite</th>
                        <th>Status</th>
                        <th>Duration</th>
                    </tr>"""

result_template = """
                    <tr>
                        <td>{testsuite}</td>
                        <td>{status}</td>
                        <td>{duration}s</td>
                    </tr>"""

footer_template = """
                </table><br>
                Overall Status: {}<br>
                Total Test Suites: {}<br>
                Passed: {}<br>
                Failed: {}<br>
                Time Taken: {}s<br>
                </body></html>"""

def generate_html_report(test_result):
    result_table = ""
    overall_status = "Passed"
    total_ts = 0
    total_failed = 0
    time_taken=0
    for ts, value in test_result.items():
        status = list(value.keys())[0]
        duration = int(list(value.values())[0])
        result_table += result_template.format(testsuite=ts, status=status, duration=duration)
        if status.lower() in ["fail", "failed"]:
            overall_status = "Failed"
            total_failed += 1
        total_ts += 1
        time_taken += duration
    footer = footer_template.format(overall_status, total_ts, total_ts-total_failed, total_failed, time_taken)
    html = header_template + result_table + footer
    with open('/tmp/sspl_test_result.html', 'w') as fObj:
        fObj.write(html)


if __name__ == '__main__':
    # Test using samples
    result = {"alerts.realstor.test_real_stor_controller_sensor1": {"Pass": 10},
              "alerts.realstor.test_sensor_real_stor_controller_actuator": {"Pass": 20},
              "ts3": {"Pass": 30}
              }
    generate_html_report(result)
